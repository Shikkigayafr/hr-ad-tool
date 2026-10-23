from app import app
from models import ActionLog

with app.app_context():
    logs = ActionLog.query.all()
    print(f"Найдено логов в базе: {len(logs)}")
    for log in logs:
        print(f"[{log.user_role}] {log.user_name}: {log.action} ({log.department})")
