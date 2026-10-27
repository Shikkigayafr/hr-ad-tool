from ldap3 import Server, Connection, ALL, MODIFY_REPLACE, MODIFY_ADD, MODIFY_DELETE, Tls
from ldap3.extend.microsoft.modifyPassword import ad_modify_password
from ldap3.utils.dn import escape_rdn
from ldap3.utils.conv import escape_filter_chars
import os
import ssl
from dotenv import load_dotenv

from secret_utils import read_secret

load_dotenv()

AD_SERVER = os.getenv("AD_SERVER", "ldaps://192.168.88.10")
AD_USER = os.getenv("AD_USER", "svc_hr@yourdomain.local")
AD_PASSWORD = read_secret("AD_PASSWORD", "ChangeMe123!")
BASE_DN = os.getenv("BASE_DN", "DC=yourdomain,DC=local")
USERS_OU = os.getenv("USERS_OU", "OU=NewUsers,DC=yourdomain,DC=local")

# Домен для UPN (login@домен) и OU с группами безопасности
AD_DOMAIN = os.getenv("AD_DOMAIN", "corp.local")
GROUPS_OU = os.getenv("GROUPS_OU", f"OU=Groups,{BASE_DN}")

# Путь к PEM-файлу с сертификатом (или корневым CA), которому доверяем при LDAPS
AD_CA_CERTS_FILE = os.getenv("AD_CA_CERTS_FILE") or None

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


def get_group_dn(role: str) -> str:
    """DN группы безопасности AD для роли (Sbis_Stager, Sbis_Main, Sbis_Senior)."""
    return f"CN={escape_rdn(role)},{GROUPS_OU}"


def build_tls():
    """TLS для LDAPS. Если задан AD_CA_CERTS_FILE — сертификат контроллера проверяется
    (цепочка и имя хоста), иначе работаем как раньше (CERT_NONE) и предупреждаем."""
    if AD_CA_CERTS_FILE:
        host = AD_SERVER.split("://")[-1].split(":")[0]
        return Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=AD_CA_CERTS_FILE, valid_names=[host])
    if not DRY_RUN:
        print("⚠️  AD_CA_CERTS_FILE не задан — сертификат LDAPS не проверяется (см. README)")
    return Tls(validate=ssl.CERT_NONE)


def get_connection():
    server = Server(AD_SERVER, port=636, use_ssl=True, tls=build_tls(), get_info=ALL)
    conn = Connection(server, user=AD_USER, password=AD_PASSWORD, auto_bind=True)
    return conn


def _split_name(full_name: str):
    """ФИО -> (фамилия, имя). Для одного слова имя остаётся пустым."""
    parts = full_name.split()
    last = parts[0] if parts else ""
    first = parts[1] if len(parts) > 1 else ""
    return last, first


def create_user(full_name: str, login: str, password: str, department: str = None, group_dn: str | None = None, email: str | None = None):
    if DRY_RUN:
        print(f"[DRY-RUN] Создал бы {full_name} / {login} в отделе {department}")
        return True, f"УСПЕХ (Режим теста): Пользователь {login} протестирован"

    conn = get_connection()
    try:
        # Формируем путь (DN) в зависимости от выбранного отдела
        if department:
            # Пользователь падает в OU=Отдел,OU=Departments,DC=corp,DC=local
            target_ou = f"OU={escape_rdn(department)},OU=Departments,{BASE_DN}"
        else:
            target_ou = USERS_OU

        dn = f"CN={escape_rdn(full_name)},{target_ou}"
        last_name, first_name = _split_name(full_name)

        # 1. Создаём отключённую учётную запись
        attributes = {
            "cn": full_name,
            "displayName": full_name,
            "sAMAccountName": login,
            "userPrincipalName": f"{login}@{AD_DOMAIN}",
            "sn": last_name,
        }
        if first_name:
            attributes["givenName"] = first_name
        if email:
            attributes["mail"] = email

        ok = conn.add(dn, object_class=["top", "person", "organizationalPerson", "user"], attributes=attributes)
        if not ok:
            return False, f"Ошибка создания: {conn.result}"

        # 2. Задаём пароль (через LDAPS). Если не вышло — удаляем заготовку,
        #    иначе при повторной попытке будет entryAlreadyExists (код 68)
        if not ad_modify_password(conn, dn, password, old_password=None):
            err = conn.result
            conn.delete(dn)
            return False, f"Ошибка пароля: {err}"

        # 3. Включаем учётную запись
        conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [512])]})

        # 4. Добавляем в группу
        if group_dn:
            ok_group = conn.modify(group_dn, {"member": [(MODIFY_ADD, [dn])]})
            if not ok_group:
                return True, f"Пользователь {login} создан, но не в группе: {conn.result}"

        return True, f"Пользователь {login} успешно создан в отделе {department}!"
    finally:
        conn.unbind()


def _find_dn(conn, login: str):
    conn.search(BASE_DN, f"(&(objectClass=user)(sAMAccountName={escape_filter_chars(login)}))", attributes=[])
    return conn.entries[0].entry_dn if conn.entries else None


def change_group(login: str, from_group_dn: str, to_group_dn: str):
    """Переносит учётку из одной группы в другую (повышение Stager -> Main)."""
    if DRY_RUN:
        print(f"[DRY-RUN] Перенёс бы {login}: {from_group_dn} -> {to_group_dn}")
        return True, "УСПЕХ (Режим теста)"

    conn = get_connection()
    try:
        dn = _find_dn(conn, login)
        if not dn:
            return False, f"Пользователь {login} не найден в AD"
        if not conn.modify(to_group_dn, {"member": [(MODIFY_ADD, [dn])]}) and conn.result.get("description") != "entryAlreadyExists":
            return False, f"Не удалось добавить в группу: {conn.result}"
        if not conn.modify(from_group_dn, {"member": [(MODIFY_DELETE, [dn])]}) and conn.result.get("description") != "unwillingToPerform":
            return False, f"Добавлен в новую группу, но не удалён из старой: {conn.result}"
        return True, "Группа изменена"
    finally:
        conn.unbind()


def delete_user(login: str):
    """Удаляет учётную запись из AD. Если её там уже нет — считаем успехом."""
    if DRY_RUN:
        print(f"[DRY-RUN] Удалил бы {login} из AD")
        return True, "УСПЕХ (Режим теста)"

    conn = get_connection()
    try:
        dn = _find_dn(conn, login)
        if not dn:
            return True, "В AD пользователя уже нет"
        if not conn.delete(dn):
            return False, f"Не удалось удалить из AD: {conn.result}"
        return True, "Удалён из AD"
    finally:
        conn.unbind()


def reset_password(login: str, new_password: str, must_change: bool = True):
    """Сбрасывает пароль учётки в AD, снимает блокировку и (по умолчанию)
    требует сменить пароль при следующем входе (pwdLastSet = 0)."""
    if DRY_RUN:
        print(f"[DRY-RUN] Сбросил бы пароль {login} (смена при входе: {must_change})")
        return True, "УСПЕХ (Режим теста)"

    conn = get_connection()
    try:
        dn = _find_dn(conn, login)
        if not dn:
            return False, f"Пользователь {login} не найден в AD"
        if not ad_modify_password(conn, dn, new_password, old_password=None):
            return False, f"Ошибка сброса пароля: {conn.result}"
        changes = {"lockoutTime": [(MODIFY_REPLACE, ["0"])]}
        if must_change:
            changes["pwdLastSet"] = [(MODIFY_REPLACE, ["0"])]
        if not conn.modify(dn, changes):
            return True, f"Пароль сброшен, но не удалось снять блокировку/включить смену пароля: {conn.result}"
        return True, "Пароль сброшен"
    finally:
        conn.unbind()
