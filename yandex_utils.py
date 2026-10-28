"""Интеграция с Яндекс 360 для бизнеса (API 360 Directory).

При создании сотрудника в панели заводит ему учётку/почтовый ящик в организации
Яндекс 360. Ошибка здесь не критична — создание в AD не отменяется (см. employee_service).

Нужны переменные окружения:
  YANDEX_ORG_ID         — числовой ID организации (можно узнать: GET /directory/v1/org)
  YANDEX_TOKEN          — OAuth-токен с правом изменять сотрудников (секрет; .env или Docker secret)
  YANDEX_DEFAULT_DEPT_ID — ID подразделения по умолчанию (1 = корневое «Все сотрудники»)
"""
import os

import requests
from dotenv import load_dotenv

from secret_utils import read_secret

load_dotenv()

YANDEX_ORG_ID = os.getenv("YANDEX_ORG_ID")
YANDEX_TOKEN = read_secret("YANDEX_TOKEN")
YANDEX_DEFAULT_DEPT_ID = int(os.getenv("YANDEX_DEFAULT_DEPT_ID", "1"))

API_BASE = "https://api360.yandex.net/directory/v1"


def _headers():
    return {"Authorization": f"OAuth {YANDEX_TOKEN}"}


def create_yandex_user(full_name, login, password, department_name=None):
    """Создаёт сотрудника (почтовый ящик) в Яндекс 360. Возвращает (ok, сообщение).

    Подразделения/группы не используем — всех кладём в корневое подразделение
    (YANDEX_DEFAULT_DEPT_ID, по умолчанию 1). department_name принимается ради единого
    интерфейса с остальными интеграциями, но на Яндекс не влияет.
    """
    if not YANDEX_ORG_ID or not YANDEX_TOKEN:
        return False, "Яндекс 360 не настроен (нужны YANDEX_ORG_ID и секрет YANDEX_TOKEN)"

    parts = full_name.split()
    last = parts[0] if parts else ""
    first = parts[1] if len(parts) > 1 else last  # Яндекс требует непустые first и last
    middle = parts[2] if len(parts) > 2 else ""

    body = {
        "name": {"first": first, "last": last, "middle": middle},
        "nickname": login,
        "password": password,
        "departmentId": YANDEX_DEFAULT_DEPT_ID,
        "passwordChangeRequired": True,  # сменить пароль при первом входе
    }

    try:
        resp = requests.post(
            f"{API_BASE}/org/{YANDEX_ORG_ID}/users",
            headers=_headers(), json=body, timeout=15,
        )
    except requests.RequestException as e:
        return False, f"Ошибка связи с Яндекс 360: {e}"

    if resp.status_code == 200:
        data = resp.json()
        email = data.get("email") or f"{login}@<домен Яндекс 360>"
        return True, f"ящик создан: {email}"

    try:
        detail = resp.json().get("message") or resp.text[:200]
    except ValueError:
        detail = resp.text[:200]
    return False, f"Яндекс 360 вернул {resp.status_code}: {detail}"
