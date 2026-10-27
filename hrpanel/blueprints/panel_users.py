"""Пользователи самой панели (admin / hr / manager) — только для администратора."""
from flask import Blueprint, g, jsonify, request

from hrpanel.extensions import db
from hrpanel.logging_config import audit
from hrpanel.security import api_roles_required
from hrpanel.services import DEPARTMENTS, PANEL_ROLES, log_action
from hrpanel.validators import LOGIN_RE, password_error
from models import User

bp = Blueprint("panel_users", __name__)


def serialize_user(u):
    return {"id": u.id, "username": u.username, "first_name": u.first_name, "role": u.role, "department": u.department}


@bp.route("/api/users", methods=["GET"])
@api_roles_required("admin")
def list_users():
    return jsonify({"ok": True, "users": [serialize_user(u) for u in User.query.order_by(User.username).all()]})


@bp.route("/api/users", methods=["POST"])
@api_roles_required("admin")
def create_panel_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    first_name = str(data.get("first_name") or "").strip()[:50] or None
    password = str(data.get("password") or "")
    role = data.get("role")
    department = data.get("department") or None

    if not LOGIN_RE.match(username):
        return jsonify({"ok": False, "message": "Логин: от 3 до 20 символов (латиница, цифры, точки, дефисы)"}), 400
    if role not in PANEL_ROLES:
        return jsonify({"ok": False, "message": "Неизвестная роль"}), 400
    if role != "admin":
        if department not in DEPARTMENTS:
            return jsonify({"ok": False, "message": "Для HR и руководителя нужно выбрать отдел"}), 400
    else:
        department = None
    err = password_error(password)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    if User.query.filter(db.func.lower(User.username) == username.lower()).first():
        return jsonify({"ok": False, "message": "Такой логин уже занят"}), 409

    user = User(username=username, first_name=first_name, role=role, department=department)
    user.set_password(password)
    db.session.add(user)
    log_action(f"создал пользователя панели {username} ({role})")
    db.session.commit()
    audit("panel_user_created", username=username, role=role)
    return jsonify({"ok": True, "message": f"Пользователь {username} создан", "user": serialize_user(user)})


@bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@api_roles_required("admin")
def delete_panel_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"ok": False, "message": "Не найден"}), 404
    if user.id == g.user.id:
        return jsonify({"ok": False, "message": "Нельзя удалить самого себя"}), 400
    username = user.username
    log_action(f"удалил пользователя панели {username}")
    db.session.delete(user)
    db.session.commit()
    audit("panel_user_deleted", username=username)
    return jsonify({"ok": True, "message": "Пользователь удалён"})


@bp.route("/api/users/<int:user_id>/password", methods=["POST"])
@api_roles_required("admin")
def reset_panel_user_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"ok": False, "message": "Не найден"}), 404
    new_password = str((request.get_json(silent=True) or {}).get("new_password") or "")
    err = password_error(new_password)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    user.set_password(new_password)
    log_action(f"сбросил пароль пользователю {user.username}")
    db.session.commit()
    audit("panel_user_password_reset", username=user.username)
    return jsonify({"ok": True, "message": f"Пароль для {user.username} изменён"})
