import secrets

from flask import Blueprint, g, jsonify, request, session

from hrpanel.extensions import db
from hrpanel.logging_config import audit
from hrpanel.security import LOCK_ATTEMPTS, client_ip, failed_attempts, login_lock_seconds
from models import LoginHistory, User

bp = Blueprint("auth", __name__)


@bp.route("/api/me")
def api_me():
    if g.user:
        return jsonify({"ok": True, "role": g.user.role, "department": g.user.department,
                        "must_change_password": g.user.must_change_password})
    return jsonify({"ok": False}), 401


@bp.route("/api/login", methods=["POST"])
def login():
    ip = client_ip()
    data = request.get_json(silent=True) or {}
    username = str(data.get("login") or "").strip()[:80]
    password = str(data.get("password") or "")

    wait = login_lock_seconds(ip, username)
    if wait:
        audit("login_blocked", username=username, ip=ip, seconds=wait)
        return jsonify({"ok": False, "seconds": wait,
                        "message": f"Заблокировано. Ждите {wait // 60} мин. {wait % 60} сек."}), 429

    user = User.query.filter_by(username=username).first() if username else None

    if user and user.check_password(password):
        session.clear()  # новая сессия после входа
        session["user_id"] = user.id
        session["csrf"] = secrets.token_hex(16)
        db.session.add(LoginHistory(username=username, ip_address=ip, success=True))
        db.session.commit()
        audit("login_success", username=username, ip=ip, role=user.role)
        return jsonify({"ok": True, "role": user.role, "must_change_password": user.must_change_password})

    db.session.add(LoginHistory(username=username, ip_address=ip, success=False))
    db.session.commit()
    audit("login_failed", username=username, ip=ip)

    wait = login_lock_seconds(ip, username)
    if wait:
        audit("login_locked", username=username, ip=ip, seconds=wait)
        return jsonify({"ok": False, "seconds": wait,
                        "message": "Слишком много попыток. Вход заблокирован на 30 минут."}), 429

    left = LOCK_ATTEMPTS - failed_attempts(ip, username)
    return jsonify({"ok": False, "message": f"Неверный логин или пароль. Осталось попыток: {max(left, 0)}"}), 401


@bp.route("/api/check_lockout", methods=["GET"])
def check_lockout():
    wait = login_lock_seconds(client_ip(), (request.args.get("login") or "").strip()[:80] or None)
    return jsonify({"locked": bool(wait), "seconds": wait})


@bp.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})
