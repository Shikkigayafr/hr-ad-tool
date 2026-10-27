"""Сессии, CSRF, блокировка входа и проверка прав."""
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import current_app, g, jsonify, redirect, request, session, url_for

from hrpanel.extensions import db
from models import LoginHistory, User

LOCK_ATTEMPTS = 5            # неудачных попыток до блокировки (на пару IP + логин)
LOCK_IP_ATTEMPTS = 30        # общий лимит с одного IP (любые логины)
LOCK_WINDOW = timedelta(minutes=30)


# --- Клиент и блокировка входа ---
def client_ip():
    # За reverse-proxy включите TRUST_PROXY=true, иначе X-Forwarded-For можно подделать
    if current_app.config.get("TRUST_PROXY"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def lock_remaining(limit, *conds):
    """Сколько секунд осталось до конца блокировки (0 — не заблокирован). Окно скользящее."""
    since = datetime.utcnow() - LOCK_WINDOW
    last_ok = db.session.query(db.func.max(LoginHistory.timestamp)).filter(*conds, LoginHistory.success.is_(True)).scalar()
    start = max(since, last_ok) if last_ok else since
    fails = LoginHistory.query.filter(*conds, LoginHistory.success.is_(False), LoginHistory.timestamp > start) \
        .order_by(LoginHistory.timestamp.desc()).limit(limit).all()
    if len(fails) < limit:
        return 0
    unlock_at = fails[-1].timestamp + LOCK_WINDOW
    return max(0, int((unlock_at - datetime.utcnow()).total_seconds()) + 1)


def login_lock_seconds(ip, username=None):
    secs = lock_remaining(LOCK_IP_ATTEMPTS, LoginHistory.ip_address == ip)
    if username:
        secs = max(secs, lock_remaining(LOCK_ATTEMPTS, LoginHistory.ip_address == ip, LoginHistory.username == username))
    return secs


def failed_attempts(ip, username):
    return LoginHistory.query.filter(
        LoginHistory.ip_address == ip, LoginHistory.username == username, LoginHistory.success.is_(False),
        LoginHistory.timestamp > datetime.utcnow() - LOCK_WINDOW).count()


# --- Декораторы прав ---
def api_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not g.user:
            return jsonify({"ok": False, "message": "Вы не авторизованы"}), 401
        return f(*args, **kwargs)
    return wrapper


def api_roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not g.user:
                return jsonify({"ok": False, "message": "Вы не авторизованы"}), 401
            if g.user.role not in roles:
                return jsonify({"ok": False, "message": "Нет прав"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def page_login_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not g.user: return redirect(url_for("pages.index"))
            if roles and g.user.role not in roles: return redirect(url_for("pages.index"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


# --- Хуки приложения ---
def register_security(app):
    @app.before_request
    def load_current_user():
        """Роль и отдел берём из БД на каждый запрос: смена роли или удаление учётки действуют сразу."""
        g.user = None
        if request.endpoint in ("static", "system.health_check"):
            return
        uid = session.get("user_id")
        if not uid:
            return
        user = db.session.get(User, uid)
        if not user:
            session.clear()
            return
        g.user = user
        session["role"] = user.role
        session["department"] = user.department
        session["username"] = user.username
        session["first_name"] = user.first_name
        if "csrf" not in session:  # сессии, созданные до появления CSRF-защиты
            session["csrf"] = secrets.token_hex(16)

    @app.before_request
    def check_csrf():
        """Все изменяющие запросы от авторизованного пользователя должны нести X-CSRF-Token."""
        if request.method in ("GET", "HEAD", "OPTIONS") or not g.user:
            return
        sent = request.headers.get("X-CSRF-Token", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            return jsonify({"ok": False, "message": "Сессия устарела, обновите страницу"}), 403

    @app.context_processor
    def inject_csrf():
        def csrf_token():
            if "csrf" not in session:
                session["csrf"] = secrets.token_hex(16)
            return session["csrf"]
        return {"csrf_token": csrf_token}
