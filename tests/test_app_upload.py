import io
import ntpath
from pathlib import Path
from unittest.mock import Mock

import pytest

from conftest import PASSWORD
from hrpanel import app_upload
from hrpanel.blueprints import app_upload as routes


def test_upload_requires_admin_and_rejects_batch_injection(as_user, monkeypatch):
    monkeypatch.setenv('APP_UPLOAD_ENABLED', 'true')
    publish = Mock()
    monkeypatch.setattr(routes, 'publish_installer', publish)
    admin = as_user('admin')

    def fields(name, arguments='', password=PASSWORD, binary=bytes.fromhex('D0CF11E0A1B11AE1')):
        return {'installer': (io.BytesIO(binary), name), 'arguments': arguments,
                'admin_password': password, 'confirm_publish': 'yes'}

    hr = as_user('hr_a')
    assert hr.get('/app-upload').status_code == 302
    assert hr.post('/api/app-upload', data=fields('setup.msi')).status_code == 403
    assert admin.get('/app-upload').status_code == 200
    assert admin.post('/api/app-upload', data=fields('setup.exe', '/S & whoami')).status_code == 400
    assert admin.post('/api/app-upload', data=fields('setup.msi', password='wrong')).status_code == 403
    publish.assert_not_called()
    response = admin.post('/api/app-upload', data=fields('setup.msi'))
    assert response.status_code == 201
    assert response.json['command'] == 'msiexec.exe /i "%~dp0setup.msi" /qn /norestart'
    publish.assert_called_once()
    pe = b'MZ' + bytes(58) + (64).to_bytes(4, 'little') + b'PE\0\0'
    response = admin.post('/api/app-upload', data=fields('setup.exe', '/S /NORESTART', binary=pe))
    assert response.status_code == 201
    assert response.json['command'] == '"%~dp0setup.exe" /S /NORESTART'


@pytest.mark.parametrize('replace_fails', [False, True])
def test_publication_preserves_batch_prefix_and_rolls_back(app, tmp_path, monkeypatch, replace_fails):
    deploy, sysvol = tmp_path / 'deploy', tmp_path / 'sysvol'
    deploy.mkdir()
    sysvol.mkdir()
    original = b'@echo off\r\nrem original\r\n'
    (sysvol / 'install_all_apps.bat').write_bytes(original)
    locations = (r'\\host\C$\Deploy', r'\\host\SYSVOL\domain\scripts')
    monkeypatch.setattr(app_upload, 'deployment_paths', lambda: ('host', locations))
    monkeypatch.setattr(app, 'instance_path', str(tmp_path))

    def local(path):
        directory, name = ntpath.split(path)
        return {locations[0]: deploy, locations[1]: sysvol}[directory] / name

    def replace(src, dst):
        if replace_fails:
            raise OSError('replace failed')
        local(src).replace(local(dst))

    monkeypatch.setattr(app_upload.smbclient, 'register_session', Mock())
    monkeypatch.setattr(app_upload.smbclient, 'open_file', lambda path, mode: local(path).open(mode))
    monkeypatch.setattr(app_upload.smbclient.path, 'exists', lambda path: local(path).exists())
    monkeypatch.setattr(app_upload.smbclient, 'stat', lambda path: local(path).stat())
    monkeypatch.setattr(app_upload.smbclient, 'rename', lambda src, dst: local(src).rename(local(dst)))
    monkeypatch.setattr(app_upload.smbclient, 'replace', replace)
    monkeypatch.setattr(app_upload.smbclient, 'remove', lambda path: local(path).unlink())
    command = app_upload.installation_command('setup.exe', '/S')
    if replace_fails:
        with pytest.raises(OSError):
            app_upload.publish_installer(io.BytesIO(b'data'), 'setup.exe', command, 4)
        assert (sysvol / 'install_all_apps.bat').read_bytes() == original
        assert not (deploy / 'setup.exe').exists() and not (sysvol / 'setup.exe').exists()
    else:
        app_upload.publish_installer(io.BytesIO(b'data'), 'setup.exe', command, 4)
        assert (sysvol / 'install_all_apps.bat').read_bytes().startswith(original)
        assert command.encode() in (sysvol / 'install_all_apps.bat').read_bytes()
        assert (deploy / 'setup.exe').read_bytes() == (sysvol / 'setup.exe').read_bytes() == b'data'
        with pytest.raises(FileExistsError):
            app_upload.publish_installer(io.BytesIO(b'else'), 'setup.exe', command, 4)
    assert not list(deploy.glob('*.tmp')) and not list(sysvol.glob('*.tmp'))
    assert next((Path(tmp_path) / 'app-upload-backups').glob('*.bat')).read_bytes() == original
