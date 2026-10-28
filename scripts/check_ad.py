"""Проверка AD для панели (ТОЛЬКО ЧТЕНИЕ): подключение по LDAPS, сертификат, OU, группы, svc_hr.

Структура сверяется с infra/ad/structure.json, поэтому один и тот же скрипт проверяет и лабораторию,
и боевой домен. Запуск из корня проекта: python scripts/check_ad.py
Код выхода 0 — всё на месте, 1 — есть проблемы.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from ldap3 import BASE, LEVEL, SUBTREE  # noqa: E402

import ad_utils  # noqa: E402

problems = []


def ok(text):
    print(f"  ✅ {text}")


def bad(text):
    problems.append(text)
    print(f"  ❌ {text}")


def main():
    with open(os.path.join(ROOT, "infra", "ad", "structure.json"), encoding="utf-8") as f:
        cfg = json.load(f)

    print(f"Сервер: {ad_utils.AD_SERVER}  учётка: {ad_utils.AD_USER}  BASE_DN: {ad_utils.BASE_DN}")
    if ad_utils.DRY_RUN:
        print("⚠️  DRY_RUN=true — панель сейчас НЕ обращается к AD (проверка подключения всё равно выполняется)")

    print("\n== Подключение")
    try:
        conn = ad_utils.get_connection()
    except Exception as e:
        bad(f"не удалось подключиться: {type(e).__name__}: {e}")
        if ad_utils.AD_CA_CERTS_FILE:
            print("     Если ошибка про сертификат: в нём должно быть имя/IP из AD_SERVER (см. infra/ad/04-Setup-LDAPS.ps1)")
        return
    ok(f"вход выполнен: {conn.extend.standard.who_am_i()}")
    if ad_utils.AD_CA_CERTS_FILE:
        ok(f"сертификат проверен ({ad_utils.AD_CA_CERTS_FILE})")
    else:
        bad("AD_CA_CERTS_FILE не задан — сертификат контроллера не проверяется (infra/ad/04-Setup-LDAPS.ps1)")

    base = ad_utils.BASE_DN
    naming = conn.server.info.other.get("defaultNamingContext", [""])[0] if conn.server.info else ""
    if naming and naming.lower() != base.lower():
        bad(f"BASE_DN={base}, а домен {naming}")

    def exists(dn):
        return conn.search(dn, "(objectClass=*)", search_scope=BASE, attributes=[])

    print("\n== OU")
    for key, name in cfg["ous"].items():
        dn = f"OU={name},{base}"
        (ok if exists(dn) else bad)(f"{key}: {dn}")
    for env_name, dn in (("GROUPS_OU", ad_utils.GROUPS_OU), ("DISABLED_OU", ad_utils.DISABLED_OU),
                         ("USERS_OU", ad_utils.USERS_OU)):
        if not exists(dn):
            bad(f"{env_name}={dn} — такой OU нет (проверьте .env)")

    print("\n== OU отделов")
    dept_root = f"OU={cfg['ous']['departments']},{base}"
    conn.search(dept_root, "(objectClass=organizationalUnit)", search_scope=LEVEL, attributes=["ou"])
    in_ad = {str(e.ou) for e in conn.entries}
    missing = [d for d in cfg["departments"] if d not in in_ad]
    if missing:
        for d in missing:
            bad(f"нет OU отдела: {d}")
    else:
        ok(f"все {len(cfg['departments'])} отделов на месте")
    for extra in sorted(in_ad - set(cfg["departments"])):
        print(f"  ⚠️ лишняя OU (нет в structure.json): {extra}")

    print("\n== Группы ролей")
    for group in cfg["groups"]:
        dn = ad_utils.get_group_dn(group)
        (ok if exists(dn) else bad)(dn)

    print("\n== Сервисная учётка")
    svc = cfg["serviceAccount"]["name"]
    conn.search(base, f"(&(objectClass=user)(sAMAccountName={svc}))", attributes=["userAccountControl"])
    if not conn.entries:
        bad(f"{svc} не найдена")
    else:
        e = conn.entries[0]
        uac = int(e.userAccountControl.value)
        expected_ou = f"OU={cfg['ous']['serviceAccounts']},{base}"
        (ok if e.entry_dn.lower().endswith(expected_ou.lower()) else bad)(
            f"{e.entry_dn}" + ("" if e.entry_dn.lower().endswith(expected_ou.lower()) else f" — ожидалась в {expected_ou}"))
        (bad if uac & 2 else ok)("учётка " + ("ОТКЛЮЧЕНА" if uac & 2 else "включена"))

    print("\n== Подозрительные учётки в отделах")
    conn.search(dept_root, "(&(objectClass=user)(!(objectClass=computer)))", search_scope=SUBTREE,
                attributes=["sAMAccountName", "userAccountControl"])
    odd = [e for e in conn.entries if int(e.userAccountControl.value) & 0x22]   # отключена или «пароль не нужен»
    for e in odd:
        print(f"  ⚠️ {e.sAMAccountName}: userAccountControl={e.userAccountControl} ({e.entry_dn})")
    if not odd:
        ok(f"нет (всего учёток в отделах: {len(conn.entries)})")
    conn.unbind()


if __name__ == "__main__":
    main()
    print("\nИТОГ:", "всё в порядке" if not problems else f"проблем: {len(problems)}")
    sys.exit(1 if problems else 0)
