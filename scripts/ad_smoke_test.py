"""Проверка всей цепочки панели на живом AD на ОДНОЙ ТЕСТОВОЙ учётке (с уборкой за собой).

Создание (Стажёр) -> повышение (Основной) -> сброс пароля -> отключение (перенос в Disabled) ->
возврат в отдел -> удаление. После каждого шага состояние перечитывается из AD.
Так проверяется, что прав у svc_hr (infra/ad/02-Configure-AD.ps1) хватает на всё, что делает панель.

    python scripts/ad_smoke_test.py --yes
    python scripts/ad_smoke_test.py --yes --dept "Офис" --login smoke.test2

Логин обязан начинаться с «smoke.» — чтобы случайно не тронуть настоящего сотрудника.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import ad_utils  # noqa: E402
from hrpanel.validators import generate_password  # noqa: E402
from saby_config import SABY_DEPARTMENTS  # noqa: E402

results = []


def state(login):
    """(dn, userAccountControl, группы) учётки или None."""
    conn = ad_utils.get_connection()
    try:
        conn.search(ad_utils.BASE_DN, f"(&(objectClass=user)(sAMAccountName={login}))",
                    attributes=["userAccountControl", "memberOf", "pwdLastSet"])
        if not conn.entries:
            return None
        e = conn.entries[0]
        groups = {str(g).split(",")[0][3:] for g in e.memberOf} if e.memberOf else set()
        return e.entry_dn, int(e.userAccountControl.value), groups, str(e.pwdLastSet)
    finally:
        conn.unbind()


def check(step, ok, message, condition, detail):
    passed = ok and condition
    results.append((step, passed))
    print(f"\n[{'OK ' if passed else 'ОШИБКА'}] {step}\n  панель: {message}\n  в AD:   {detail}")
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--login", default="smoke.test")
    parser.add_argument("--dept", default="Офис", choices=list(SABY_DEPARTMENTS))
    parser.add_argument("--yes", action="store_true", help="подтверждаю: работаю с AD из .env")
    args = parser.parse_args()

    if ad_utils.DRY_RUN:
        sys.exit("DRY_RUN=true — проверять нечего, панель не обращается к AD")
    if not args.login.startswith("smoke."):
        sys.exit("Логин тестовой учётки должен начинаться с «smoke.»")
    if not args.yes:
        sys.exit(f"Будет создана и удалена учётка {args.login} в {ad_utils.AD_SERVER}. Запустите с --yes")
    if state(args.login):
        sys.exit(f"{args.login} уже есть в AD — удалите её или выберите другой --login")

    login, dept = args.login, args.dept
    stager, main_group = ad_utils.get_group_dn("Sbis_Stager"), ad_utils.get_group_dn("Sbis_Main")
    dept_ou = f"OU={dept},OU=Departments,{ad_utils.BASE_DN}".lower()
    disabled_ou = ad_utils.DISABLED_OU.lower()
    print(f"AD: {ad_utils.AD_SERVER}  учётка панели: {ad_utils.AD_USER}  тест: {login} в «{dept}»")

    try:
        ok, msg = ad_utils.create_user("Смоук Тест", login, generate_password(), department=dept, group_dn=stager)
        s = state(login)
        if not check("1. Создание + группа Sbis_Stager", ok, msg,
                     bool(s) and s[0].lower().endswith(dept_ou) and s[1] == 512 and "Sbis_Stager" in s[2], s):
            return

        ok, msg = ad_utils.change_group(login, stager, main_group)
        s = state(login)
        check("2. Повышение Sbis_Stager -> Sbis_Main", ok, msg,
              "Sbis_Main" in s[2] and "Sbis_Stager" not in s[2], s[2])

        ok, msg = ad_utils.reset_password(login, generate_password(), must_change=True)
        s = state(login)
        check("3. Сброс пароля + «сменить при входе»", ok, msg, s[3].startswith("1601"), f"pwdLastSet={s[3]}")

        ok, msg = ad_utils.disable_user(login, reason="smoke-тест", group_dn=main_group)
        s = state(login)
        check("4. Отключение (514, перенос в Disabled, без группы)", ok, msg,
              s[1] == 514 and s[0].lower().endswith(disabled_ou) and "Sbis_Main" not in s[2], s)

        ok, msg = ad_utils.enable_user(login, dept, group_dn=main_group)
        s = state(login)
        check("5. Возврат (512, обратно в отдел, группа)", ok, msg,
              s[1] == 512 and s[0].lower().endswith(dept_ou) and "Sbis_Main" in s[2], s)
    finally:
        if state(login):
            ok, msg = ad_utils.delete_user(login)
            check("6. Удаление", ok, msg, state(login) is None, "учётки нет" if state(login) is None else "ОСТАЛАСЬ")

    print("\nИТОГ:", ", ".join(f"{step.split('.')[0]}:{'OK' if p else 'ОШИБКА'}" for step, p in results))
    if not all(p for _, p in results):
        print("Ошибки прав — допишите нужное право в infra/ad/02-Configure-AD.ps1 и проверьте снова.")
        sys.exit(1)


if __name__ == "__main__":
    main()
