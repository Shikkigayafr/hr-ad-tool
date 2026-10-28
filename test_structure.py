import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = os.getenv("SABY_PASSWORD")
ORG_INN = os.getenv("SABY_ORG_INN")

DEPT_UUID = "64035429-e72d-4767-8b22-302f0a94f782"
DEPT_NAME = "Отдел исходящих звонков"
POSITION_ID = "305d7061-926c-4661-b502-cc6750ae956c"

def main():
    manager = SABYManager(login=LOGIN, password=PASSWORD)
    login = "test.final.1"  # НОВЫЙ ЛОГИН

    print("--- ШАГ 1: Создаем карточку (без НашаОрганизация) ---")
    query_card = {
        "Параметр": {
            "Сотрудник": {
                "Фамилия": "Тестов", "Имя": "Финал", "Отчество": "Тестович",
                "Логин": login, "Пароль": "Test12345!", "ДоступВСистему": "Да",
                "ИдентификаторИС": login, "ВнешнийИдентификатор": login
                # Убрали НашаОрганизация!
            }
        }
    }
    res = manager.send_query("СБИС.ЗаписатьСотрудника", query_card)
    if 'error' in res:
        print("Ошибка карточки:", res['error'])
        return
    print("Карточка создана:", res.get('Сотрудник', {}).get('Идентификатор'))

    print("\n--- ШАГ 2: Привязываем к отделу через UpdatePosition (без НашаОрганизация) ---")
    query_pos = {
        "filter": {
            "employee": {"extId": login},
            # Убрали organization!
            "position": {
                "dateFrom": "22.10.2026",
                "department": {"extId": DEPT_UUID, "name": DEPT_NAME},
                "position": {"id": POSITION_ID, "name": "Менеджер"},
                "typeEmployment": "Основное место работы"
            }
        }
    }
    pos_res = manager.send_query("sabyEmployee.UpdatePosition", query_pos)
    print("Ответ UpdatePosition:", json.dumps(pos_res, indent=4, ensure_ascii=False, default=str))

if __name__ == "__main__":
    main()