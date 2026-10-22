import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = os.getenv("SABY_PASSWORD")
ORG_INN = os.getenv("SABY_ORG_INN")
ORG_UUID = "1d05d561-3b11-4a46-8cba-62ae4b67298e"

def main():
    manager = SABYManager(login=LOGIN, password=PASSWORD)

    print("--- 1. Создаем ТЕСТОВЫЙ кадровый отдел ---")
    
    create_dept_query = {
        "departments": [
            {
                "title": "ТЕСТ_Офис_Кадровый",
                "type": 0,
                "structureType": 1,
                "parent": {"id": ORG_UUID},
                "organization": {"inn": ORG_INN}
            }
        ]
    }
    
    try:
        result = manager.send_query("sabyDepartment.Update", create_dept_query)
        print("Ответ Saby:", json.dumps(result, indent=4, ensure_ascii=False))
        
        # ИСПРАВЛЕНИЕ: Saby возвращает список строк (UUID)
        if isinstance(result, list) and len(result) > 0:
            new_dept_uuid = result[0]  # Берем первую строку из списка
        else:
            print("❌ Не удалось получить UUID созданного отдела.")
            return
            
        print(f"✅ Создан кадровый отдел с UUID: {new_dept_uuid}")
            
    except Exception as e:
        print(f"❌ Ошибка создания отдела: {e}")
        return

    print("\n--- 2. Создаем сотрудника и привязываем к тестовому отделу ---")
    
    login = "test.saby.cadre.4"  # НОВЫЙ ЛОГИН
    query_card = {
        "Параметр": {
            "Сотрудник": {
                "Фамилия": "Тестов", "Имя": "Кадр", "Отчество": "Тестович",
                "Логин": login, "Пароль": "Test12345!", "ДоступВСистему": "Да",
                "ВнешнийИдентификатор": login,
                "НашаОрганизация": {"СвФЛ": {"ИНН": ORG_INN}}
            }
        }
    }
    
    try:
        res_card = manager.send_query("СБИС.ЗаписатьСотрудника", query_card)
        if 'error' in res_card:
            print(f"❌ Ошибка создания карточки: {res_card['error']}")
            return
    except Exception as e:
        print(f"❌ Ошибка создания карточки: {e}")
        return

    query_position = {
        "filter": {
            "employee": {"extId": login},
            "organization": {"inn": ORG_INN, "kpp": ""},
            "position": {
                "organization": {"inn": ORG_INN, "kpp": ""},
                "position": {"id": "305d7061-926c-4661-b502-cc6750ae956c"}, # Менеджер
                "dateFrom": "22.10.2026"
            },
            "department": {"id": new_dept_uuid} # UUID нового кадрового отдела
        }
    }

    try:
        pos_result = manager.send_query("sabyEmployee.UpdatePosition", query_position)
        print("Ответ UpdatePosition:", json.dumps(pos_result, indent=4, ensure_ascii=False))
        
        if 'error' in pos_result:
             print(f"❌ Ошибка привязки: {pos_result['error']}")
        else:
             print("✅ Сотрудник успешно привязан к ТЕСТОВОМУ кадровому отделу!")
             
    except Exception as e:
        print(f"❌ Ошибка привязки: {e}")

if __name__ == "__main__":
    main()