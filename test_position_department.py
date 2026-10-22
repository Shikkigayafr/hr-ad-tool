import os
import json
from datetime import datetime
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()

manager = SABYManager(
    login=os.getenv("SABY_LOGIN"),
    password=os.getenv("SABY_PASSWORD")
)

ORG_INN = os.getenv("SABY_ORG_INN", "021800952356")
DEPARTMENT_ID = "65610"
DEPARTMENT_UUID = "64035429-e72d-4767-8b22-302f0a94f782"
DEPARTMENT_NAME = "Отдел исходящих звонков"
POSITION_ID = "305d7061-926c-4661-b502-cc6750ae956c"
POSITION_NAME = "Менеджер"

# ВАЖНО: укажите extId (логин / ИдентификаторИС) существующего тестового сотрудника
TEST_EXT_ID = "test.saby.check.1"
TODAY = datetime.now().strftime("%d.%m.%Y")

payload = {
    "filter": {
        "employee": {
            "extId": TEST_EXT_ID
        },
        "position": {
            "dateFrom": TODAY,
            "organization": {
                "inn": ORG_INN,
                "kpp": ""
            },
            "department": {
                "code": "",
                "extId": DEPARTMENT_UUID,
                "name": DEPARTMENT_NAME
            },
            "position": {
                "id": POSITION_ID,
                "name": POSITION_NAME
            },
            "typeEmployment": "Основное место работы"
        }
    }
}

if __name__ == "__main__":
    print("Эталонный payload для sabyEmployee.UpdatePosition:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
