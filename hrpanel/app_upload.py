"""Публикация установщиков в две папки AD и добавление команды в SYSVOL."""
import ntpath
import re
import shutil
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4

import smbclient
from flask import current_app

import ad_utils

MAX_INSTALLER_SIZE = 300 * 1024 * 1024
_publish_lock = Lock()
_filename = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}\.(?:exe|msi)", re.IGNORECASE)
_arguments = re.compile(r'[A-Za-z0-9 /_.:=,+\\"-]{0,512}')
_reserved = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)


def installation_command(name, arguments):
    if not _filename.fullmatch(name) or _reserved.fullmatch(name.split('.')[0].rstrip()):
        raise ValueError("Имя файла должно содержать латиницу, цифры, пробелы, точки, дефисы или подчёркивания и расширение MSI/EXE")
    path = f'"%~dp0{name}"'
    if name.lower().endswith('.msi'):
        return f'msiexec.exe /i {path} /qn /norestart'
    if not _arguments.fullmatch(arguments) or arguments.count('"') % 2:
        raise ValueError("Параметры EXE содержат недопустимые символы или незакрытые кавычки")
    return f'{path} {arguments}'.rstrip()


def validate_installer(stream, name):
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if not 0 < size <= MAX_INSTALLER_SIZE:
        raise ValueError("Размер файла должен быть от 1 байта до 300 МБ")
    if name.lower().endswith('.msi'):
        valid = stream.read(8) == bytes.fromhex('D0CF11E0A1B11AE1')
    else:
        header = stream.read(64)
        valid = False
        if len(header) == 64 and header[:2] == b'MZ':
            offset = int.from_bytes(header[60:64], 'little')
            if 64 <= offset <= size - 4:
                stream.seek(offset)
                valid = stream.read(4) == b'PE\0\0'
    stream.seek(0)
    if not valid:
        raise ValueError("Формат файла не соответствует расширению установщика")
    return size


def deployment_paths():
    server = ad_utils.AD_SERVER
    host = urlsplit(server if '://' in server else 'ldaps://' + server).hostname
    if not host or not ad_utils.AD_USER or not ad_utils.AD_PASSWORD:
        raise RuntimeError("Для публикации нужен настроенный сервер AD и его учётная запись")
    return host, (rf'\\{host}\C$\Deploy', rf'\\{host}\SYSVOL\{ad_utils.AD_DOMAIN}\scripts')


def publish_installer(stream, name, command, size):
    if not _publish_lock.acquire(blocking=False):
        raise FileExistsError("Другая публикация уже выполняется. Повторите после её завершения.")
    try:
        _publish(stream, name, command, size)
    finally:
        _publish_lock.release()


def _publish(stream, name, command, size):
    host, locations = deployment_paths()
    smbclient.register_session(host, username=ad_utils.AD_USER, password=ad_utils.AD_PASSWORD,
                               encrypt=True, auth_protocol='ntlm', connection_timeout=10)
    batch = ntpath.join(locations[1], 'install_all_apps.bat')
    targets = [ntpath.join(folder, name) for folder in locations]
    if any(smbclient.path.exists(path) for path in targets):
        raise FileExistsError("Файл с таким именем уже есть. Укажите другое имя публикации.")

    with smbclient.open_file(batch, 'rb') as remote:
        original = remote.read(1024 * 1024 + 1)
    if len(original) > 1024 * 1024 or b'\0' in original or original.endswith(b'\x1a'):
        raise RuntimeError("Формат существующего батника не подходит для безопасного дописывания")

    upload_id = uuid4().hex
    backup_dir = Path(current_app.instance_path) / 'app-upload-backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / f'{upload_id}.bat').write_bytes(original)
    updated = original + f'\r\nREM Published application {upload_id}\r\n{command}\r\n'.encode('ascii')
    temporary = []
    published = []
    replacing = False
    try:
        for target in targets:
            pending = ntpath.join(ntpath.dirname(target), f'.app-upload-{upload_id}.tmp')
            with smbclient.open_file(pending, 'xb') as remote:
                temporary.append(pending)
                stream.seek(0)
                shutil.copyfileobj(stream, remote, length=1024 * 1024)
            if smbclient.stat(pending).st_size != size:
                raise OSError("Размер загруженной копии не совпал")
            smbclient.rename(pending, target)
            temporary.remove(pending)
            published.append(target)

        pending_batch = ntpath.join(locations[1], f'.app-batch-{upload_id}.tmp')
        with smbclient.open_file(pending_batch, 'xb') as remote:
            temporary.append(pending_batch)
            remote.write(updated)
        with smbclient.open_file(batch, 'rb') as remote:
            if remote.read(len(original) + 1) != original:
                raise RuntimeError("Батник изменился во время загрузки. Повторите публикацию.")
        replacing = True
        smbclient.replace(pending_batch, batch)
        temporary.remove(pending_batch)
    except Exception:
        # Если ответ на замену потерялся, сначала выясняем состояние батника.
        if replacing:
            with smbclient.open_file(batch, 'rb') as remote:
                actual = remote.read(len(updated) + 1)
            if actual == updated:
                return
            replacing = actual != original
        if not replacing:
            for path in published:
                _remove_temporary(path)
        raise
    finally:
        for path in temporary:
            _remove_temporary(path)


def _remove_temporary(path):
    try:
        smbclient.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        current_app.logger.warning("Не удалось убрать файл незавершённой публикации")
