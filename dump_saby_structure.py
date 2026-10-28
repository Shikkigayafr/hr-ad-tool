import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = os.getenv("SABY_PASSWORD")
ORG_INN = os.getenv("SABY_ORG_INN")

# UUID "Отдела исходящих звонков"
DEPT_UUID = "64035429-e72d-4767-8b22-302f0a94f782"
DEPT_NAME = "Отдел исходящих звонков"
POSITION_ID = "305d7061-926c-4661-b502-cc6750ae956c" # Менеджер

def step(title, data):
    print(f"\n{'='*70}")
    print(f" {title}")
    print(f"{'='*70}")
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=4, ensure_ascii=False, default=str))
    else:
        print(data)

def main():
    manager = SABYManager(login=LOGIN, password=PASSWORD)
    login = "test.debug.step.1" # <--- МЕНЯЙ КАЖДЫЙ РАЗ

    # --- ШАГ 1: Создание карточки ---
    step("ШАГ 1: Создание карточки (СБИС.ЗаписатьСотрудника)", {
        "Логин": login,
        "ФИО": "Тестов Дебаг Степыч",
        "Организация": ORG_INN
    })
    
    query_card = {
        "Параметр": {
            "Сотрудник": {
                "Фамилия": "Тестов", "Имя": "Дебаг", "Отчество": "Степыч",
                "Логин": login, "Пароль": "Test12345!", "ДоступВСистему": "Да",
                "ИдентификаторИС": login, "ВнешнийИдентификатор": login,
                "НашаОрганизация": {"СвФЛ": {"ИНН": ORG_INN}}
            }
        }
    }
    try:
        res_card = manager.send_query("СБИС.ЗаписатьСотрудника", query_card)
        if 'error' in res_card:
            step("❌ ОШИБКА на ШАГЕ 1", res_card['error'])
            return
        step("✅ ШАГ 1 УСПЕШЕН. Ответ Saby:", res_card.get('result', res_card))
    except Exception as e:
        step("❌ ИСКЛЮЧЕНИЕ на ШАГЕ 1", str(e))
        return

    # --- ШАГ 2: Попытка привязать к отделу ---
    step("ШАГ 2: Привязка к отделу (sabyEmployee.UpdatePosition)", {
        "Отдел": DEPT_NAME,
        "UUID отдела": DEPT_UUID,
        "Должность ID": POSITION_ID
    })

    query_pos = {
        "filter": {
            "employee": {"extId": login},
            "organization": {"inn": ORG_INN, "kpp": ""},
            "position": {
                "dateFrom": "22.10.2026",
                "organization": {"inn": ORG_INN, "kpp": ""},
                "department": {"extId": DEPT_UUID, "name": DEPT_NAME},
                "position": {"id": POSITION_ID, "name": "Менеджер"},
                "typeEmployment": "Основное место работы"
            }
        }
    }
    
    try:
        res_pos = manager.send_query("sabyEmployee.UpdatePosition", query_pos)
        if 'error' in res_pos:
            step("❌ ОШИБКА на ШАГЕ 2", res_pos['error'])
            print("\n>>> ВЫВОД: Saby принял запрос, но вернул ошибку. Возможно, проблема в структуре department.")
        else:
            step("✅ ШАГ 2 УСПЕШЕН (Saby вернул 200). Ответ:", res_pos)
            
            # Проверяем, что именно Saby записал в department
            dept_in_response = res_pos.get('position', {}).get('department', {})
            step("Что Saby записал в department:", dept_in_response)
            
            if dept_in_response.get('extId') == DEPT_UUID:
                print("\n>>> ВЫВОД: Saby ПРИНЯЛ отдел (в кадровой структуре).")
                print(">>> НО: визуально в управленческой структуре он может не отображаться (это ограничение Saby).")
            else:
                print("\n>>> ВЫВОД: Saby ПРОИГНОРИРОВАЛ отдел и записал что-то другое.")
    except Exception as e:
        step("❌ ИСКЛЮЧЕНИЕ на ШАГЕ 2", str(e))

if __name__ == "__main__":
    main()