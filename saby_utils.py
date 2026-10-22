import os
from dotenv import load_dotenv
from pysaby import SABYManager
from saby_config import SABY_DEPARTMENTS, SABY_ORG_INN, SABY_DEPARTMENT_UUIDS

load_dotenv()

SABY_LOGIN = os.getenv("SABY_LOGIN")
SABY_PASSWORD = os.getenv("SABY_PASSWORD")

def create_saby_user(full_name, login, password, department_name, position_id="305d7061-926c-4661-b502-cc6750ae956c"):
    dept_id = SABY_DEPARTMENTS.get(department_name)
    dept_uuid = SABY_DEPARTMENT_UUIDS.get(department_name)
    
    if not dept_id or not dept_uuid:
        return False, f"Отдел '{department_name}' не найден"

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
                    "ДатаПриема": "22.10.2026",
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
                    "dateFrom": "22.10.2026",
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