import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from secret_utils import read_secret
from pysaby import SABYManager
from saby_config import SABY_DEPARTMENTS, SABY_ORG_INN, SABY_DEPARTMENT_UUIDS

load_dotenv()

SABY_LOGIN = os.getenv("SABY_LOGIN")
SABY_PASSWORD = read_secret("SABY_PASSWORD")

def create_saby_user(full_name, login, password, department_name, position_id="305d7061-926c-4661-b502-cc6750ae956c"):
    dept_id = SABY_DEPARTMENTS.get(department_name)
    dept_uuid = SABY_DEPARTMENT_UUIDS.get(department_name)
    
    if not dept_id or not dept_uuid:
        return False, f"Отдел '{department_name}' не найден"

    today = datetime.now().strftime("%d.%m.%Y")

    try:
        manager = SABYManager(login=SABY_LOGIN, password=SABY_PASSWORD)

        name_parts = full_name.split()
        last_name = name_parts[0] if len(name_parts) > 0 else ""
        first_name = name_parts[1] if len(name_parts) > 1 else ""
        middle_name = name_parts[2] if len(name_parts) > 2 else ""

        # --- ШАГ 1: Создаем карточку (сразу с подразделением) ---
        query_card = {
            "Параметр": {
                "Сотрудник": {
                    "Фамилия": last_name,
                    "Имя": first_name,
                    "Отчество": middle_name,
                    "Логин": login,
                    "Пароль": password,
                    "ДоступВСистему": "Да",
                    "ИдентификаторИС": login,
                    "ВнешнийИдентификатор": login,
                    "ДатаПриема": today,
                    "ТипТрудоустройства": "Основное место работы",
                    "НашаОрганизация": {"СвФЛ": {"ИНН": SABY_ORG_INN}},
                    "Должность": {
                        "Идентификатор": position_id,
                        "Название": "Менеджер"
                    },
                    "Подразделение": {
                        "Идентификатор": str(dept_id),
                        "Название": department_name
                    }
                }
            }
        }
        
        result = manager.send_query("СБИС.ЗаписатьСотрудника", query_card)
        if 'error' in result:
            return False, f"Ошибка карточки: {result['error']}"

        # --- ШАГ 2: Привязываем должность (organization в filter + department внутри position) ---
        query_position = {
            "filter": {
                "employee": {
                    "extId": login 
                },
                "organization": {
                    "inn": SABY_ORG_INN,
                    "kpp": ""
                },
                "position": {
                    "dateFrom": today,
                    "organization": {
                        "inn": SABY_ORG_INN,
                        "kpp": ""
                    },
                    "department": {
                        "extId": dept_uuid,
                        "name": department_name
                    },
                    "position": {
                        "id": position_id,
                        "name": "Менеджер"
                    },
                    "typeEmployment": "Основное место работы"
                }
            }
        }

        pos_result = manager.send_query("sabyEmployee.UpdatePosition", query_position)
        
        if 'error' in pos_result:
            return True, f"Сотрудник {login} создан. Должность не привязана: {pos_result.get('message', '')}"

        return True, f"Сотрудник {login} создан и зачислен в '{department_name}'!"

    except Exception as e:
        return False, f"Ошибка: {str(e)}"


def dismiss_saby_user(login=None, full_name=None, saby_id=None):
    """Увольняет сотрудника в СБИС (НЕ удаляет — карточка и документы/сделки сохраняются).

    Проставляет ДатаУвольнения = ВЧЕРА, чтобы увольнение считалось уже наступившим и доступ
    блокировался сразу (если поставить сегодняшнюю, доступ может сняться только со следующего дня).

    Сотрудник ищется по числовому `saby_id` (Идентификатор из СБИС.СписокСотрудников) — это
    надёжнее всего и работает для любых сотрудников. Если id нет — по `login` (подходит для
    заведённых через панель, у них ИдентификаторИС = login). Возвращает (ok, сообщение).
    """
    if not saby_id and not login:
        return False, "СБИС: нужен либо saby_id, либо login"

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")
    today = datetime.now().strftime("%d.%m.%Y")

    if saby_id:
        base = {"Идентификатор": int(saby_id), "ДоступВСистему": "Нет",
                "НашаОрганизация": {"СвФЛ": {"ИНН": SABY_ORG_INN}}}
    else:
        base = {
            "Логин": login,
            "ИдентификаторИС": login,
            "ВнешнийИдентификатор": login,
            "ДоступВСистему": "Нет",
            "НашаОрганизация": {"СвФЛ": {"ИНН": SABY_ORG_INN}},
        }
    if full_name:
        parts = full_name.split()
        base["Фамилия"] = parts[0] if parts else ""
        base["Имя"] = parts[1] if len(parts) > 1 else ""
        if len(parts) > 2:
            base["Отчество"] = parts[2]

    def _write(date_str):
        employee = dict(base, **{"ДатаУвольнения": date_str})
        return SABYManager(login=SABY_LOGIN, password=SABY_PASSWORD).send_query(
            "СБИС.ЗаписатьСотрудника", {"Параметр": {"Сотрудник": employee}})

    def _is_hire_conflict(x):
        # СБИС не даёт дату увольнения раньше даты приёма (pysaby кидает исключение с этим текстом)
        return "раньше даты приема" in str(x).lower()

    # Пробуем «вчера»; если конфликт с датой приёма (принят сегодня) — «сегодня».
    for date_str in (yesterday, today):
        try:
            result = _write(date_str)
        except Exception as e:
            if date_str == yesterday and _is_hire_conflict(e):
                continue
            return False, f"Ошибка СБИС при увольнении: {e}"
        err = result.get("error") if isinstance(result, dict) else None
        if err:
            if date_str == yesterday and _is_hire_conflict(err):
                continue
            return False, f"СБИС не уволил: {err}"
        return True, f"уволен в СБИС (дата {date_str}, доступ закрыт)"
    return False, "СБИС: не удалось уволить (конфликт даты)"


def find_saby_id(full_name):
    """Ищет числовой Идентификатор сотрудника в СБИС по ФИО (среди действующих).

    Возвращает (saby_id, note). saby_id=None, если не найден или совпадений несколько
    (в этом случае увольнять вслепую нельзя — вернём None и причину).
    """
    want = " ".join(full_name.split()).strip().lower()
    try:
        manager = SABYManager(login=SABY_LOGIN, password=SABY_PASSWORD)
        res = manager.send_query(
            "СБИС.СписокСотрудников",
            {"Параметр": {"Фильтр": {"НашаОрганизация": {"СвФЛ": {"ИНН": SABY_ORG_INN}}}}})
    except Exception as e:
        return None, f"ошибка запроса СБИС: {e}"

    employees = res.get("Сотрудник") if isinstance(res, dict) else None
    if isinstance(employees, dict):
        employees = [employees]

    matches = []
    for e in (employees or []):
        fio = " ".join(p for p in (e.get("Фамилия"), e.get("Имя"), e.get("Отчество")) if p).strip().lower()
        if fio == want:
            matches.append(e.get("Идентификатор"))

    if len(matches) == 1:
        return matches[0], "найден"
    if not matches:
        return None, "в СБИС не найден"
    return None, f"неоднозначно: {len(matches)} совпадений по ФИО"
