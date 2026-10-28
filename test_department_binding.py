"""Диагностика: почему сотрудник в Saby попадает в корень структуры, а не в отдел нужного ИП.

По умолчанию скрипт ТОЛЬКО ЧИТАЕТ данные Saby:
    python test_department_binding.py
    python test_department_binding.py --dept "Офис"

Создать тестового сотрудника в БОЕВОМ Saby и посмотреть, куда он лёг (нужен новый логин):
    python test_department_binding.py --create --login test.bind.2
    python test_department_binding.py --create --login test.bind.3 --variant no-org
    python test_department_binding.py --create --login test.bind.4 --variant no-dept

Подобрать рабочий формат поля Подразделение на УЖЕ созданном тестовом сотруднике (Идентификатор из карточки):
    python test_department_binding.py --try-formats 213710

Варианты карточки (СБИС.ЗаписатьСотрудника):
    panel   - как делает панель (saby_utils.py): НашаОрганизация + Подразделение по числовому ID
    no-org  - без НашаОрганизация (гипотеза из CLAUDE.md: тогда отдел ищется в управленческой структуре)
    no-dept - как старая версия этого скрипта: без Подразделение (ожидаемо ляжет в корень)
"""
import argparse
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from pysaby import SABYManager

from saby_config import SABY_DEPARTMENT_UUIDS, SABY_DEPARTMENTS, SABY_ORG_INN
from secret_utils import read_secret

load_dotenv()
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = read_secret("SABY_PASSWORD")

ORG_UUID = "1d05d561-3b11-4a46-8cba-62ae4b67298e"  # ИП Мазинова (узел организации в структуре)
POSITION_ID = "305d7061-926c-4661-b502-cc6750ae956c"  # Менеджер
STRUCTURE_TYPES = {0: "управленческое", 1: "кадровое", 2: "кадровое + управленческое"}

findings = []  # выводы, которые печатаются в конце


def step(title, data=None):
    print(f"\n{'=' * 70}\n {title}\n{'=' * 70}")
    if data is not None:
        print(json.dumps(data, indent=4, ensure_ascii=False, default=str) if isinstance(data, (dict, list)) else data)


def finding(text):
    findings.append(text)
    print(f">>> {text}")


def query(manager, method, params):
    """send_query, который не падает: при ошибке возвращает {'error': ...}."""
    try:
        return manager.send_query(method, params)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def structure_type(dept):
    raw = dept.get("structureType")
    try:
        return f"{raw} ({STRUCTURE_TYPES[int(raw)]})"
    except (TypeError, ValueError, KeyError):
        return f"{raw} (?)"


# --- Часть 1: только чтение ---
def check_organizations(manager):
    step("1. Наши организации (СБИС.СписокНашихОрганизаций)")
    res = query(manager, "СБИС.СписокНашихОрганизаций", {"Фильтр": {}})
    orgs = as_list(res.get("НашаОрганизация")) if isinstance(res, dict) else []
    if not orgs:
        print(res)
        finding("Не удалось получить список организаций")
        return
    found = False
    for org in orgs:
        info = org.get("СвФЛ") or org.get("СвЮЛ") or {}
        inn = info.get("ИНН", "")
        name = info.get("НазваниеПолное") or info.get("Название") or ""
        mark = "  <-- SABY_ORG_INN" if inn == SABY_ORG_INN else ""
        kind = "ИП" if "СвФЛ" in org else "ЮЛ"
        print(f" - [{kind}] {name} (ИНН {inn}){mark}")
        found = found or inn == SABY_ORG_INN
    if len(orgs) > 1:
        finding(f"В аккаунте {len(orgs)} организаций: без явной организации Saby может положить сотрудника не в тот ИП")
    if not found:
        finding("ИНН из SABY_ORG_INN НЕ найден среди наших организаций — сотрудник не может попасть в этот ИП")


def check_department(manager, dept_name):
    dept_uuid = SABY_DEPARTMENT_UUIDS.get(dept_name)
    dept_id = SABY_DEPARTMENTS.get(dept_name)
    step(f"2. Узел ИП и отдел «{dept_name}» (sabyDepartment.Read)",
         {"ORG_UUID": ORG_UUID, "UUID отдела": dept_uuid, "числовой ID отдела": dept_id})

    for label, uuid in (("ИП", ORG_UUID), ("Отдел", dept_uuid)):
        res = query(manager, "sabyDepartment.Read", {"departments": [uuid]})
        items = as_list(res.get("department")) if isinstance(res, dict) and "department" in res else as_list(res)
        print(f"\n--- {label} ---")
        print(json.dumps(res, indent=4, ensure_ascii=False, default=str))
        if not items or not isinstance(items[0], dict) or "error" in items[0]:
            finding(f"{label}: sabyDepartment.Read не нашёл узел {uuid}")
            continue
        d = items[0]
        print(f"structureType: {structure_type(d)}; parent: {d.get('parent')}")
        if label == "Отдел":
            if str(d.get("structureType")) == "1":
                finding(f"«{dept_name}» — только КАДРОВОЕ подразделение: в управленческом дереве его нет, "
                        f"поэтому визуально сотрудник окажется в корне")
            parent = json.dumps(d.get("parent"), ensure_ascii=False, default=str)
            if ORG_UUID not in parent:
                finding(f"Родитель «{dept_name}» — не узел ИП ({ORG_UUID}): отдел висит в другой ветке/организации")


def check_department_lists(manager, dept_name):
    dept_uuid = SABY_DEPARTMENT_UUIDS.get(dept_name)
    dept_id = str(SABY_DEPARTMENTS.get(dept_name))
    step("3. В каком списке подразделений есть отдел (СБИС.СписокПодразделений)")
    filters = {
        "с организацией (юридическая структура)": {"НашаОрганизация": {"СвФЛ": {"ИНН": SABY_ORG_INN}}},
        "без организации (управленческая структура)": {},
    }
    for label, flt in filters.items():
        res = query(manager, "СБИС.СписокПодразделений", {"Параметр": {"Фильтр": flt}})
        depts = as_list(res.get("Подразделение")) if isinstance(res, dict) else []
        match = [d for d in depts if str(d.get("Идентификатор")) == dept_id
                 or d.get("ВнешнийИдентификатор") == dept_uuid or d.get("Название") == dept_name]
        print(f"\n--- {label}: всего {len(depts)} ---")
        if "error" in res:
            print(res["error"])
        for d in match:
            print(json.dumps(d, indent=4, ensure_ascii=False, default=str))
        if not match:
            print(f"«{dept_name}» не найден")
        elif str(match[0].get("Идентификатор")) != dept_id:
            finding(f"{label}: у «{dept_name}» Идентификатор={match[0].get('Идентификатор')}, "
                    f"а в saby_config.py {dept_id} — панель передаёт ID из другой структуры")
        else:
            print(f"Идентификатор совпадает с saby_config.py ({dept_id})")


# --- Часть 2: создание (только с --create) ---
def create_and_bind(manager, login, dept_name, variant):
    dept_uuid = SABY_DEPARTMENT_UUIDS[dept_name]
    dept_id = str(SABY_DEPARTMENTS[dept_name])
    today = datetime.now().strftime("%d.%m.%Y")

    card = {
        "Фамилия": "Тестов", "Имя": "Бинд", "Отчество": "Тестович",
        "Логин": login, "Пароль": "Test12345!", "ДоступВСистему": "Да",
        "ИдентификаторИС": login, "ВнешнийИдентификатор": login,
        "ДатаПриема": today, "ТипТрудоустройства": "Основное место работы",
        "Должность": {"Идентификатор": POSITION_ID, "Название": "Менеджер"},
    }
    if variant != "no-org":
        card["НашаОрганизация"] = {"СвФЛ": {"ИНН": SABY_ORG_INN}}
    if variant != "no-dept":
        card["Подразделение"] = {"Идентификатор": dept_id, "Название": dept_name}

    query_card = {"Параметр": {"Сотрудник": card}}
    safe_card = json.loads(json.dumps(query_card, ensure_ascii=False))
    safe_card["Параметр"]["Сотрудник"]["Пароль"] = "***"
    step(f"4. Создаём карточку, вариант «{variant}» (СБИС.ЗаписатьСотрудника)", safe_card)
    res = query(manager, "СБИС.ЗаписатьСотрудника", query_card)
    print("Ответ:", json.dumps(res, indent=4, ensure_ascii=False, default=str))
    if isinstance(res, dict) and "error" in res:
        finding(f"Карточка не создана: {res['error']}")
        return
    returned = res.get("Сотрудник", res) if isinstance(res, dict) else {}
    got_dept = returned.get("Подразделение") if isinstance(returned, dict) else None
    print(f"Подразделение в ответе карточки: {got_dept}")
    if variant == "no-dept":
        finding("Карточка создана без Подразделение — Saby кладёт такого сотрудника в корень (так было в старом скрипте)")
    elif not (got_dept or {}).get("Название"):
        finding("Saby не вернул Подразделение в карточке — переданный ID отдела, скорее всего, проигнорирован")

    query_pos = {
        "filter": {
            "employee": {"extId": login},
            "organization": {"inn": SABY_ORG_INN, "kpp": ""},
            "position": {
                "dateFrom": today,
                "organization": {"inn": SABY_ORG_INN, "kpp": ""},
                "department": {"extId": dept_uuid, "name": dept_name},
                "position": {"id": POSITION_ID, "name": "Менеджер"},
                "typeEmployment": "Основное место работы",
            },
        }
    }
    step("5. Привязка к отделу (sabyEmployee.UpdatePosition)", query_pos)
    pos = query(manager, "sabyEmployee.UpdatePosition", query_pos)
    print("Ответ:", json.dumps(pos, indent=4, ensure_ascii=False, default=str))
    if isinstance(pos, dict) and "error" in pos:
        finding(f"UpdatePosition вернул ошибку: {pos['error']}")
    else:
        dept_in_resp = pos.get("position", {}).get("department", {}) if isinstance(pos, dict) else {}
        if dept_in_resp.get("extId") == dept_uuid:
            finding("UpdatePosition принял отдел — но это КАДРОВАЯ структура; в управленческом дереве "
                    "место определяет только Подразделение в карточке")
        else:
            finding(f"UpdatePosition записал другой отдел: {dept_in_resp}")
    print(f"\nТеперь откройте в Saby «Сотрудники» -> {login} и посмотрите, где он в дереве. "
          f"Запишите результат варианта «{variant}».")


def read_card_department(manager, emp_id):
    res = query(manager, "СБИС.ПрочитатьСотрудника", {"Параметр": {"Сотрудник": {"Идентификатор": emp_id}}})
    return ((res.get("Сотрудник") or {}).get("Подразделение") or {}).get("Название", "") if isinstance(res, dict) else ""


def try_department_formats(manager, emp_id, dept_name):
    """Перезаписывает Подразделение у СУЩЕСТВУЮЩЕГО тестового сотрудника разными форматами,
    после каждого перечитывает карточку. Останавливается на первом сработавшем."""
    dept_uuid = SABY_DEPARTMENT_UUIDS[dept_name]
    dept_id = str(SABY_DEPARTMENTS[dept_name])
    card = query(manager, "СБИС.ПрочитатьСотрудника", {"Параметр": {"Сотрудник": {"Идентификатор": emp_id}}})
    emp = card.get("Сотрудник") if isinstance(card, dict) else None
    if not emp:
        finding(f"Сотрудник {emp_id} не найден: {card}")
        return
    base = {k: emp[k] for k in ("Идентификатор", "Фамилия", "Имя", "Отчество", "ВнешнийИдентификатор") if k in emp}
    org = {"НашаОрганизация": {"СвФЛ": {"ИНН": SABY_ORG_INN}}}

    formats = [
        ("Идентификатор (число) + Название, без организации", {"Идентификатор": dept_id, "Название": dept_name}, {}),
        ("только Идентификатор (число)", {"Идентификатор": dept_id}, org),
        ("только Название", {"Название": dept_name}, org),
        ("Идентификатор = UUID", {"Идентификатор": dept_uuid}, org),
        ("ВнешнийИдентификатор = UUID", {"ВнешнийИдентификатор": dept_uuid}, org),
        ("только Название, без организации", {"Название": dept_name}, {}),
    ]
    step(f"6. Подбор формата Подразделение для {emp_id} {emp.get('Логин', '')}",
         f"Сейчас в карточке: «{read_card_department(manager, emp_id)}»")
    for label, dept_value, extra in formats:
        params = {"Параметр": {"Сотрудник": {**base, **extra, "Подразделение": dept_value}}}
        res = query(manager, "СБИС.ЗаписатьСотрудника", params)
        error = res.get("error") if isinstance(res, dict) else None
        now = read_card_department(manager, emp_id)
        status = "СРАБОТАЛО" if now == dept_name else "нет"
        print(f"\n[{status}] {label}\n  отправили: {json.dumps(dept_value, ensure_ascii=False)}"
              f"{' + НашаОрганизация' if extra else ''}\n  в карточке: «{now}»" + (f"\n  ошибка: {error}" if error else ""))
        if now == dept_name:
            finding(f"Рабочий формат Подразделение: {label} -> {json.dumps(dept_value, ensure_ascii=False)}"
                    f"{' + НашаОрганизация' if extra else ''}. Его нужно перенести в saby_utils.py")
            return
    finding("Ни один формат не записал Подразделение через СБИС.ЗаписатьСотрудника — "
            "нужен другой метод (например, кадровый документ приёма) или вопрос в поддержку Saby")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dept", default="Отдел исходящих звонков", choices=sorted(SABY_DEPARTMENT_UUIDS))
    parser.add_argument("--create", action="store_true", help="создать тестового сотрудника в БОЕВОМ Saby")
    parser.add_argument("--login", help="новый логин тестового сотрудника (обязателен с --create)")
    parser.add_argument("--variant", default="panel", choices=["panel", "no-org", "no-dept"])
    parser.add_argument("--try-formats", metavar="EMP_ID",
                        help="Идентификатор СУЩЕСТВУЮЩЕГО тестового сотрудника: подобрать формат Подразделение")
    parser.add_argument("--yes", action="store_true", help="не спрашивать подтверждение (для запуска из другого скрипта)")
    args = parser.parse_args()

    def confirmed(question):
        return args.yes or input(f"\n{question} Введите yes: ").strip().lower() == "yes"

    if args.try_formats:
        if not LOGIN or not PASSWORD or not SABY_ORG_INN:
            sys.exit("Не заданы SABY_LOGIN / SABY_PASSWORD / SABY_ORG_INN в .env")
        manager = SABYManager(login=LOGIN, password=PASSWORD)
        if confirmed(f"Менять Подразделение у сотрудника {args.try_formats} в БОЕВОМ Saby?"):
            try_department_formats(manager, args.try_formats, args.dept)
        else:
            print("Отменено, ничего не изменено")
        step("ИТОГ")
        print("\n".join(f"- {f}" for f in findings))
        return

    if not LOGIN or not PASSWORD or not SABY_ORG_INN:
        sys.exit("Не заданы SABY_LOGIN / SABY_PASSWORD / SABY_ORG_INN в .env")
    if args.create and not args.login:
        sys.exit("С --create нужен новый логин: --login test.bind.N")

    manager = SABYManager(login=LOGIN, password=PASSWORD)
    check_organizations(manager)
    check_department(manager, args.dept)
    check_department_lists(manager, args.dept)

    if args.create:
        if confirmed(f"Создать сотрудника {args.login} в БОЕВОМ Saby?"):
            create_and_bind(manager, args.login, args.dept, args.variant)
        else:
            print("Отменено, ничего не создано")

    step("ИТОГ")
    print("\n".join(f"- {f}" for f in findings) or "- Явных проблем в структуре не найдено: "
          "запустите с --create и сравните варианты panel / no-org")


if __name__ == "__main__":
    main()
