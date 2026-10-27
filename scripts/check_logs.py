import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # корень проекта

from app import app
from models import ActionLog

with app.app_context():
    logs = ActionLog.query.all()
    print(f"Найдено логов в базе: {len(logs)}")
    for log in logs:
        print(f"[{log.user_role}] {log.user_name}: {log.action} ({log.department})")
