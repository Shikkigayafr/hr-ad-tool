import os
import json
from dotenv import load_dotenv
from pysaby import SABYManager

load_dotenv()

manager = SABYManager(
    login=os.getenv("SABY_LOGIN"),
    password=os.getenv("SABY_PASSWORD")
)

tests = [
    ("sabyDepartment.List", {}),
    ("sabyDepartment.GetList", {}),
    ("sabyDepartment.Read", {
        "departments": [
            "64035429-e72d-4767-8b22-302f0a94f782"
        ]
    }),
    ("sabyDepartment.Read", {
        "id": "64035429-e72d-4767-8b22-302f0a94f782"
    }),
]

for method, payload in tests:
    print("\n" + "=" * 80)
    print(method)
    print("=" * 80)
    print("REQUEST:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    try:
        result = manager.send_query(method, payload)

        print("\nRESPONSE:")
        print(json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str
        ))

    except Exception as e:
        print("\nERROR:")
        print(repr(e))