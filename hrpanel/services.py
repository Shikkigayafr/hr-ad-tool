"""Общая бизнес-логика: журнал действий, оповещения, выборки с учётом прав."""
from datetime import datetime

from flask import g

from hrpanel.extensions import db, socketio
from models import ActionLog, Employee
from saby_config import SABY_DEPARTMENTS

DEPARTMENTS = list(SABY_DEPARTMENTS.keys())
EMPLOYEE_ROLES = ("Sbis_Stager", "Sbis_Main", "Sbis_Senior")
PANEL_ROLES = ("admin", "hr", "manager")


def iso(dt):
    """datetime (UTC в БД) -> ISO-строка с Z, браузер сам переведёт в местное время."""
    return dt.isoformat() + "Z" if dt else None


def relative_time(dt):
    minutes = int((datetime.utcnow() - dt).total_seconds() // 60)
    if minutes < 1: return "только что"
    if minutes < 60: return f"{minutes} мин. назад"
    if minutes < 1440: return f"{minutes // 60} ч. назад"
    return f"{minutes // 1440} дн. назад"


def actor_name():
    return g.user.first_name or g.user.username


def log_action(text):
    """Пишет событие в журнал (commit делает вызывающий код)."""
    db.session.add(ActionLog(user_name=actor_name(), user_role=g.user.role,
                             department=g.user.department, action=text))


def notify_action(text):
    """Отправляет событие только тем, кто имеет право его видеть (как в /api/logs)."""
    payload = {"user": actor_name(), "action": text, "role": g.user.role}
    socketio.emit("new_log", payload, to="role:admin")
    if g.user.role == "hr" and g.user.department:
        socketio.emit("new_log", payload, to=f"hr:{g.user.department}")
    if g.user.department:
        socketio.emit("new_log", payload, to=f"manager:{g.user.department}")


def scoped_employees():
    """Админ видит всех, остальные — только свой отдел."""
    q = Employee.query
    if g.user.role != "admin":
        q = q.filter(Employee.department == g.user.department)
    return q


def visible_logs_query():
    q = ActionLog.query
    if g.user.role == "admin": return q
    if g.user.role == "hr": return q.filter_by(user_role="hr", department=g.user.department)
    if g.user.role == "manager": return q.filter_by(department=g.user.department)
    return q.filter(db.false())
