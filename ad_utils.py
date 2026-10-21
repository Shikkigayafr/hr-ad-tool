from ldap3 import Server, Connection, ALL, MODIFY_REPLACE, MODIFY_ADD
from ldap3.extend.microsoft.modifyPassword import ad_modify_password
import os
from dotenv import load_dotenv

# Загружаем переменные из файла .env
load_dotenv()

AD_SERVER = os.getenv("AD_SERVER", "ldap://192.168.88.10")
AD_USER = os.getenv("AD_USER", "svc_hr@yourdomain.local")
AD_PASSWORD = os.getenv("AD_PASSWORD", "ChangeMe123!")
BASE_DN = os.getenv("BASE_DN", "DC=yourdomain,DC=local")
USERS_OU = os.getenv("USERS_OU", "OU=NewUsers,DC=yourdomain,DC=local")

# Читаем флаг DRY_RUN из .env
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

def get_connection():
    server = Server(AD_SERVER, get_info=ALL)
    conn = Connection(server, user=AD_USER, password=AD_PASSWORD, auto_bind=True)
    return conn

def create_user(full_name: str, login: str, password: str, group_dn: str | None = None):
    """
    Создаёт пользователя в AD.
    Возвращает (ok: bool, message: str).
    """
    if DRY_RUN:
        print(f"[DRY-RUN] Создал бы {full_name} / {login}")
        if group_dn:
            print(f"[DRY-RUN] Добавил бы в группу {group_dn}")
        return True, f"УСПЕХ (Режим теста): Пользователь {login} протестирован (Группа: {group_dn or 'не указана'})"

    conn = get_connection()
    dn = f"CN={full_name},{USERS_OU}"

    # 1. Создаём отключённую учётную запись
    ok = conn.add(dn, object_class=["top", "person", "organizationalPerson", "user"], attributes={
        "cn": full_name,
        "displayName": full_name,
        "sAMAccountName": login,
        "userPrincipalName": f"{login}@yourdomain.local",
        "givenName": full_name.split()[0] if full_name else "",
        "sn": full_name.split()[-1] if full_name else "",
    })
    if not ok:
        return False, f"Не удалось создать запись: {conn.result}"

    # 2. Задаём пароль
    if not ad_modify_password(conn, dn, password):
        return False, f"Не удалось задать пароль: {conn.result}"

    # 3. Включаем учётную запись
    conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [512])]})

    # 4. Добавляем в группу (вот наш новый кусок)
    if group_dn:
        ok_group = conn.modify(group_dn, {"member": [(MODIFY_ADD, [dn])]})
        if not ok_group:
            # Если юзер создался, но в группу не попал — сообщаем об этом
            return True, f"Пользователь {login} создан, но не добавлен в группу: {conn.result}"

    conn.unbind()
    return True, f"Пользователь {login} создан и добавлен в группу"