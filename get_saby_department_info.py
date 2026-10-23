import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = os.getenv("SABY_PASSWORD")

def main():
    manager = SABYManager(login=LOGIN, password=PASSWORD)
    
    print("--- Проверка структуры ИП Мазинова ---")
    
    # UUID организации "ИП Мазинова Назиля Ириковна" (из твоего лога)
    org_uuid = "1d05d561-3b11-4a46-8cba-62ae4b67298e"
    
    query = {
        "departments": [org_uuid]
    }
    
    try:
        result = manager.send_query("sabyDepartment.Read", query)
        print(json.dumps(result, indent=4, ensure_ascii=False))
        
        if 'department' in result:
            dept = result['department']
            if isinstance(dept, list) and len(dept) > 0:
                dept = dept[0]
            print(f"\nНазвание: {dept.get('name')}")
            print(f"structureType: {dept.get('structureType')}")
            if dept.get('structureType') == "0":
                print("ВЫВОД: Это УПРАВЛЕНЧЕСКОЕ подразделение")
            elif dept.get('structureType') == "1":
                print("ВЫВОД: Это КАДРОВОЕ подразделение")
            else:
                print(f"ВЫВОД: Тип не распознан (structureType: {dept.get('structureType')})")
                
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    main()