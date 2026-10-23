import os
from dotenv import load_dotenv

load_dotenv()

# Читаем ИНН из окружения
SABY_ORG_INN = os.getenv("SABY_ORG_INN")

# Читаем числовые ID отделов из окружения
SABY_DEPARTMENTS = {
    "Отдел горячих продаж": os.getenv("SABY_DEPT_HOT_SALES", "158456"),
    "Стажеры ТП": os.getenv("SABY_DEPT_STAGERS_TP", "136943"),
    "Колл Центр": os.getenv("SABY_DEPT_CALL_CENTER", "128206"),
    "Координатор": os.getenv("SABY_DEPT_COORDINATOR", "104978"),
    "СММ": os.getenv("SABY_DEPT_SMM", "76240"),
    "Контроль качества": os.getenv("SABY_DEPT_QUALITY", "75844"),
    "Продление": os.getenv("SABY_DEPT_PROLONG", "69749"),
    "Офис": os.getenv("SABY_DEPT_OFFICE", "66287"),
    "Отдел исходящих звонков": os.getenv("SABY_DEPT_OUTGOING", "65610"),
    "Отдел входящих звонков": os.getenv("SABY_DEPT_INCOMING", "65609"),
    "Отдел развития": os.getenv("SABY_DEPT_DEVELOPMENT", "15700"),
    "Техническая поддержка": os.getenv("SABY_DEPT_TECH_SUPPORT", "8162"),
    "Облако": os.getenv("SABY_DEPT_CLOUD", "82298"),
    "Удаленные": os.getenv("SABY_DEPT_REMOTE", "150651"),
}

# UUID подразделений (ВнешнийИдентификатор / extId из СБИС.СписокПодразделений)
SABY_DEPARTMENT_UUIDS = {
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

