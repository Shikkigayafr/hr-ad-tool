import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()
LOGIN = os.getenv("SABY_LOGIN")
PASSWORD = os.getenv("SABY_PASSWORD")

# UUID отделов (ВнешнийИдентификатор из СБИС.СписокПодразделений)
DEPARTMENTS = {
    "Отдел горячих продаж": "019f002c-76d9-7759-8710-34ffb96f5b0f",
    "Стажеры ТП": "31c568ce-2a84-4512-89af-9ed4efa2a1a7",
    "Колл Центр": "0b07d3a2-e170-4acb-bdef-2ab06eeed6bc",
    "Координатор": "147429cc-9ff5-4829-a884-c5eb75c93fb4",
    "СММ": "a8428792-5278-4456-ba5e-8b9abb5ee650",
    "Контроль качества": "ffb5fbcf-60e6-4d9b-a61d-6fe58650b42f",
    "Продление": "64528648-b716-4606-9d8c-3ace461a6930",
    "Офис": "7514a1b3-532e-4fc3-a3ed-50333e3db2f6",
    "Отдел исходящих звонков": "64035429-e72d-4767-8b22-302f0a94f782",
    "Отдел входящих звонков": "ad568a5f-df81-40ea-944a-57c2076688c4",
    "Отдел развития": "a2f1605b-b9ff-42f9-8fbf-f2d89a8cf5d2",
    "Техническая поддержка": "faa7d695-fccc-4212-97d0-a516376f6017",
    "Облако": "2f3ca39d-d43a-48a3-93f5-a4c4fff30595",
    "Удаленные": "019eca90-19be-7b88-9f9c-5da2cdbde1b2",
}

def main():
    manager = SABYManager(login=LOGIN, password=PASSWORD)
    
    print(f"{'Отдел':<30} | {'structureType':<15} | {'type':<10}")
    print("-" * 65)
    
    for name, uuid in DEPARTMENTS.items():
        query = {"departments": [uuid]}
        try:
            result = manager.send_query("sabyDepartment.Read", query)
            if isinstance(result, list) and len(result) > 0:
                dept = result[0]
                st = dept.get('structureType', 'N/A')
                t = dept.get('type', 'N/A')
                
                st_text = {0: "Управленческое", 1: "Кадровое", 2: "Кадровое+Управленческое"}.get(st, "?")
                print(f"{name:<30} | {st_text:<15} | {t}")
            else:
                print(f"{name:<30} | ОШИБКА: {result}")
        except Exception as e:
            print(f"{name:<30} | ОШИБКА: {e}")

if __name__ == "__main__":
    main()