from ldap3 import Server, Connection, ALL, MODIFY_REPLACE, MODIFY_ADD, Tls
from ldap3.extend.microsoft.modifyPassword import ad_modify_password
import os
import ssl
from dotenv import load_dotenv

load_dotenv()

AD_SERVER = os.getenv("AD_SERVER", "ldaps://192.168.88.10")
AD_USER = os.getenv("AD_USER", "svc_hr@yourdomain.local")
AD_PASSWORD = os.getenv("AD_PASSWORD", "ChangeMe123!")
BASE_DN = os.getenv("BASE_DN", "DC=yourdomain,DC=local")
USERS_OU = os.getenv("USERS_OU", "OU=NewUsers,DC=yourdomain,DC=local")

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

def get_connection():
    tls_config = Tls(validate=ssl.CERT_NONE)
    server = Server(AD_SERVER, port=636, use_ssl=True, tls=tls_config, get_info=ALL)
    conn = Connection(server, user=AD_USER, password=AD_PASSWORD, auto_bind=True)
    return conn

def create_user(full_name: str, login: str, password: str, department: str = None, group_dn: str | None = None):
    if DRY_RUN:
        print(f"[DRY-RUN] Создал бы {full_name} / {login} в отделе {department}")
        return True, f"УСПЕХ (Режим теста): Пользователь {login} протестирован"

    conn = get_connection()
    
    # Формируем путь (DN) в зависимости от выбранного отдела
    if department:
        # Пользователь падает в OU=Отдел,OU=Departments,DC=corp,DC=local
        target_ou = f"OU={department},OU=Departments,{BASE_DN}"
    else:
        target_ou = USERS_OU
        
    dn = f"CN={full_name},{target_ou}"

    # 1. Создаём отключённую учётную запись
    ok = conn.add(dn, object_class=["top", "person", "organizationalPerson", "user"], attributes={
        "cn": full_name,
        "displayName": full_name,
        "sAMAccountName": login,
        "userPrincipalName": f"{login}@corp.local",
        "givenName": full_name.split()[0] if full_name else "",
        "sn": full_name.split()[-1] if full_name else "",
    })
    if not ok:
        conn.unbind()
        return False, f"Ошибка создания: {conn.result}"

    # 2. Задаём пароль (через LDAPS)
    if not ad_modify_password(conn, dn, password, old_password=None):
        conn.unbind()
        return False, f"Ошибка пароля: {conn.result}"

    # 3. Включаем учётную запись
    conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [512])]})

    # 4. Добавляем в группу
    if group_dn:
        ok_group = conn.modify(group_dn, {"member": [(MODIFY_ADD, [dn])]})
        if not ok_group:
            conn.unbind()
            return True, f"Пользователь {login} создан, но не в группе: {conn.result}"

    conn.unbind()
    return True, f"Пользователь {login} успешно создан в отделе {department}!"