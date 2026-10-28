import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = os.getenv("SABY_PASSWORD")
ORG_INN = os.getenv("SABY_ORG_INN")
ORG_UUID = "1d05d561-3b11-4a46-8cba-62ae4b67298e" # ИП Мазинова

def main():
    manager = SABYManager(login=LOGIN, password=PASSWORD)
    
    # 1. Создаем отдел с structureType: 2 (кадровое + управленческое)
    print("--- Создаем тестовый отдел (structureType: 2) ---")
    create_dept = {
        "departments": [{
            "title": "ТЕСТ_Визуал_Отдел",
            "type": 0, # 0 = подразделение
            "structureType": 2, # 2 = кадровое + управленческое
            "parent": {"id": ORG_UUID},
            "organization": {"inn": ORG_INN}
        }]
    }
    
    try:
        dept_res = manager.send_query("sabyDepartment.Update", create_dept)
        print("Ответ:", json.dumps(dept_res, indent=4, ensure_ascii=False))
        new_dept_uuid = dept_res[0] if isinstance(dept_res, list) else dept_res
        print(f"Создан отдел с UUID: {new_dept_uuid}")
    except Exception as e:
        print(f"Ошибка создания отдела: {e}")
        return
    
    # 2. Создаем сотрудника и привязываем к этому отделу
    print("\n--- Создаем сотрудника ---")
    login = "test.visual.1" # НОВЫЙ ЛОГИН
    query_card = {
        "Параметр": {
            "Сотрудник": {
                "Фамилия": "Тестов", "Имя": "Визуал", "Отчество": "Тестович",
                "Логин": login, "Пароль": "Test12345!", "ДоступВСистему": "Да",
                "ИдентификаторИС": login, "ВнешнийИдентификатор": login,
                "НашаОрганизация": {"СвФЛ": {"ИНН": ORG_INN}}
            }
        }
    }
    manager.send_query("СБИС.ЗаписатьСотрудника", query_card)
    
    print("\n--- Привязываем к отделу (structureType: 2) ---")
    query_pos = {
        "filter": {
            "employee": {"extId": login},
            "organization": {"inn": ORG_INN, "kpp": ""},
            "position": {
                "dateFrom": "22.10.2026",
                "organization": {"inn": ORG_INN, "kpp": ""},
                "department": {"extId": new_dept_uuid, "name": "ТЕСТ_Визуал_Отдел"},
                "position": {"id": "305d7061-926c-4661-b502-cc6750ae956c", "name": "Менеджер"},
                "typeEmployment": "Основное место работы"
            }
        }
    }
    pos_res = manager.send_query("sabyEmployee.UpdatePosition", query_pos)
    print("Ответ UpdatePosition:", json.dumps(pos_res, indent=4, ensure_ascii=False, default=str))

if __name__ == "__main__":
    main()