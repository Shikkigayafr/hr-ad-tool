"""Главная: статистика, график, лента событий, полный журнал и история входов."""
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from hrpanel.extensions import db
from hrpanel.security import api_login_required
from hrpanel.services import iso, relative_time, scoped_employees, visible_logs_query
from models import ActionLog, Employee, LoginHistory

bp = Blueprint("dashboard", __name__)


@bp.route("/api/stats")
@api_login_required
def api_stats():
    display_name = g.user.first_name or g.user.username.capitalize()
    emps = scoped_employees().order_by(Employee.created_at.desc()).all()
    week_ago = datetime.utcnow() - timedelta(days=7)

    employees_list = [{
        "id": e.id, "full_name": e.full_name, "role": e.role, "department": e.department,
        "created_at": iso(e.created_at),
    } for e in emps]

    return jsonify({
        "ok": True,
        "total": len(emps),
        "stagers": sum(1 for e in emps if e.role == "Sbis_Stager"),
        "staff": sum(1 for e in emps if e.role != "Sbis_Stager"),
        "new_week": sum(1 for e in emps if e.created_at and e.created_at >= week_ago),
        "employees": employees_list,
        "user_name": display_name,
        "user_avatar": g.user.avatar,
        "role": g.user.role,
    })


@bp.route("/api/logs")
@api_login_required
def get_logs():
    logs = visible_logs_query().order_by(ActionLog.timestamp.desc()).limit(10).all()
    return jsonify({"ok": True, "logs": [
        {"user": l.user_name, "action": l.action, "time": relative_time(l.timestamp)} for l in logs
    ]})


@bp.route("/api/logs/all")
@api_login_required
def get_logs_all():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
    search = (request.args.get("q") or "").strip()

    q = visible_logs_query()
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(ActionLog.action.ilike(like), ActionLog.user_name.ilike(like)))

    total = q.count()
    logs = q.order_by(ActionLog.timestamp.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "ok": True, "total": total, "page": page, "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
        "logs": [{"user": l.user_name, "role": l.user_role, "department": l.department,
                  "action": l.action, "time": iso(l.timestamp)} for l in logs],
    })


@bp.route("/api/chart_data")
@api_login_required
def api_chart_data():
    days, counts = [], []
    today = datetime.utcnow().date()
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        start = datetime.combine(date, datetime.min.time())
        end = start + timedelta(days=1)
        days.append(date.strftime("%d.%m"))
        counts.append(scoped_employees().filter(Employee.created_at >= start, Employee.created_at < end).count())
    return jsonify({"ok": True, "labels": days, "data": counts})


@bp.route("/api/login_history")
@api_login_required
def get_login_history():
    # Админ видит все входы, остальные — только свои
    q = LoginHistory.query
    if g.user.role != "admin":
        q = q.filter_by(username=g.user.username)
    history = q.order_by(LoginHistory.timestamp.desc()).limit(10).all()
    return jsonify({"ok": True, "history": [{
        "username": h.username, "ip": h.ip_address or "Неизвестно",
        "success": h.success, "time": iso(h.timestamp),
    } for h in history]})
