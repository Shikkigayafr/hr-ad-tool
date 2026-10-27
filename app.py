from flask import Flask, render_template, request, jsonify, session, redirect, url_for, make_response, g
from flask.json.provider import DefaultJSONProvider
from flask_socketio import SocketIO, join_room
from werkzeug.exceptions import HTTPException
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime, timedelta
from io import StringIO
import click
import csv
import os
import re
import secrets
import traceback

load_dotenv()

from ad_utils import create_user, get_group_dn, change_group, delete_user as ad_delete_user
from models import db, User, Employee, ActionLog, LoginHistory
from saby_config import SABY_DEPARTMENTS
from backup_utils import backup_database

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    # Без SECRET_KEY сессии живут только до перезапуска. Задайте его в .env!
    print("⚠️  SECRET_KEY не задан в .env — сгенерирован временный ключ (сессии сбросятся при перезапуске)")
    _secret = secrets.token_hex(32)
app.secret_key = _secret
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///hr.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # аватарки не больше 2 МБ

app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# true включать, когда панель открывается по HTTPS
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True

# --- ФИКС КИРИЛЛИЦЫ В JSON ---
class CustomJSONProvider(DefaultJSONProvider):
    ensure_ascii = False
app.json = CustomJSONProvider(app)

db.init_app(app)

# Socket.IO: по умолчанию только тот же origin. Другие можно перечислить в CORS_ORIGINS через запятую
_cors = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
socketio = SocketIO(app, cors_allowed_origins=_cors or None)

# Флаги интеграций (по умолчанию выключены — безопасно для разработки без AD/Saby)
SABY_ENABLED = os.environ.get('SABY_ENABLED', 'false').lower() == 'true'
AD_SYNC_CHANGES = os.environ.get('AD_SYNC_CHANGES', 'false').lower() == 'true'

DEPARTMENTS = list(SABY_DEPARTMENTS.keys())
EMPLOYEE_ROLES = ('Sbis_Stager', 'Sbis_Main', 'Sbis_Senior')
PANEL_ROLES = ('admin', 'hr', 'manager')

LOGIN_RE = re.compile(r'^[a-zA-Z0-9._-]{3,20}$')
EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
NAME_RE = re.compile(r"^[\w .'-]+$")

LOCK_ATTEMPTS = 5            # неудачных попыток до блокировки
LOCK_IP_ATTEMPTS = 30        # общий лимит с одного IP (любые логины)
LOCK_WINDOW = timedelta(minutes=30)


# --- НАСТРОЙКА БЭКАПОВ ---
def start_backup_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=backup_database, trigger="cron", hour=3, minute=0, args=[app])
    scheduler.start()
    print("✅ Планировщик бэкапов запущен (каждый день в 03:00)")

# Запускаем его только в production (чтобы не дублировалось при debug=True)
if os.environ.get('FLASK_ENV') == 'production' or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    start_backup_scheduler(app)


# --- ВСПОМОГАТЕЛЬНОЕ ---
def iso(dt):
    """datetime (UTC в БД) -> ISO-строка с Z, браузер сам переведёт в местное время."""
    return dt.isoformat() + 'Z' if dt else None


def relative_time(dt):
    minutes = int((datetime.utcnow() - dt).total_seconds() // 60)
    if minutes < 1: return "только что"
    if minutes < 60: return f"{minutes} мин. назад"
    if minutes < 1440: return f"{minutes // 60} ч. назад"
    return f"{minutes // 1440} дн. назад"


def password_error(password):
    """Те же правила, что и на фронтенде. None — пароль подходит."""
    if not password or len(password) < 8 or not re.search(r'[A-Z]', password) \
            or not re.search(r'[0-9]', password) or not re.search(r'[^A-Za-z0-9]', password):
        return "Пароль слишком простой: нужны 8+ символов, заглавная буква, цифра и спецсимвол"
    return None


def csv_safe(value):
    """Защита от формул в Excel (=, +, -, @ в начале ячейки)."""
    value = '' if value is None else str(value)
    return "'" + value if value[:1] in ('=', '+', '-', '@') else value


def client_ip():
    # За reverse-proxy включите TRUST_PROXY=true, иначе X-Forwarded-For можно подделать
    if os.environ.get('TRUST_PROXY', 'false').lower() == 'true':
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.remote_addr or ''


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


def actor_name():
    return g.user.first_name or g.user.username


def log_action(text):
    """Пишет событие в журнал (commit делает вызывающий код)."""
    db.session.add(ActionLog(user_name=actor_name(), user_role=g.user.role,
                             department=g.user.department, action=text))


def notify_action(text):
    """Отправляет событие только тем, кто имеет право его видеть (как в /api/logs)."""
    payload = {'user': actor_name(), 'action': text, 'role': g.user.role}
    socketio.emit('new_log', payload, to='role:admin')
    if g.user.role == 'hr' and g.user.department:
        socketio.emit('new_log', payload, to=f'hr:{g.user.department}')
    if g.user.department:
        socketio.emit('new_log', payload, to=f'manager:{g.user.department}')


def scoped_employees():
    """Админ видит всех, остальные — только свой отдел."""
    q = Employee.query
    if g.user.role != 'admin':
        q = q.filter(Employee.department == g.user.department)
    return q


def visible_logs_query():
    q = ActionLog.query
    if g.user.role == 'admin': return q
    if g.user.role == 'hr': return q.filter_by(user_role='hr', department=g.user.department)
    if g.user.role == 'manager': return q.filter_by(department=g.user.department)
    return q.filter(db.false())


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
            if not g.user: return redirect(url_for('index'))
            if roles and g.user.role not in roles: return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def load_current_user():
    """Роль и отдел берём из БД на каждый запрос: смена роли или удаление учётки действуют сразу."""
    g.user = None
    if request.endpoint in ('static', 'health_check'):
        return
    uid = session.get('user_id')
    if not uid:
        return
    user = db.session.get(User, uid)
    if not user:
        session.clear()
        return
    g.user = user
    session['role'] = user.role
    session['department'] = user.department
    session['username'] = user.username
    session['first_name'] = user.first_name
    if 'csrf' not in session:  # сессии, созданные до появления CSRF-защиты
        session['csrf'] = secrets.token_hex(16)


@app.before_request
def check_csrf():
    """Все изменяющие запросы к API от авторизованного пользователя должны нести X-CSRF-Token."""
    if request.method in ('GET', 'HEAD', 'OPTIONS') or not g.user:
        return
    sent = request.headers.get('X-CSRF-Token', '')
    if not sent or not secrets.compare_digest(sent, session.get('csrf', '')):
        return jsonify({"ok": False, "message": "Сессия устарела, обновите страницу"}), 403


@app.context_processor
def inject_csrf():
    def csrf_token():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(16)
        return session['csrf']
    return {'csrf_token': csrf_token}


# --- SOCKET.IO ---
@socketio.on('connect')
def on_connect():
    uid = session.get('user_id')
    user = db.session.get(User, uid) if uid else None
    if not user:
        return False  # неавторизованных не пускаем
    if user.role == 'admin': join_room('role:admin')
    if user.role == 'hr' and user.department: join_room(f'hr:{user.department}')
    if user.role == 'manager' and user.department: join_room(f'manager:{user.department}')


# --- СТРАНИЦЫ ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/create")
@page_login_required()
def page_create():
    return render_template("create.html", departments=DEPARTMENTS)

@app.route("/employees")
@page_login_required()
def page_employees():
    return render_template("employees.html")

@app.route("/profile")
@page_login_required()
def page_profile():
    return render_template("profile.html")

@app.route("/logs")
@page_login_required()
def page_logs():
    return render_template("logs.html")

@app.route("/users")
@page_login_required('admin')
def page_users():
    return render_template("users.html", departments=DEPARTMENTS)


# --- API: общее ---
@app.route("/api/me")
def api_me():
    if g.user:
        return jsonify({"ok": True, "role": g.user.role, "department": g.user.department})
    return jsonify({"ok": False}), 401


@app.route("/api/stats")
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
        "stagers": sum(1 for e in emps if e.role == 'Sbis_Stager'),
        "staff": sum(1 for e in emps if e.role != 'Sbis_Stager'),
        "new_week": sum(1 for e in emps if e.created_at and e.created_at >= week_ago),
        "employees": employees_list,
        "user_name": display_name,
        "user_avatar": g.user.avatar,
        "role": g.user.role,
    })


@app.route("/api/logs")
@api_login_required
def get_logs():
    logs = visible_logs_query().order_by(ActionLog.timestamp.desc()).limit(10).all()
    return jsonify({"ok": True, "logs": [
        {"user": l.user_name, "action": l.action, "time": relative_time(l.timestamp)} for l in logs
    ]})


@app.route("/api/logs/all")
@api_login_required
def get_logs_all():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, max(1, request.args.get('per_page', 25, type=int)))
    search = (request.args.get('q') or '').strip()

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


@app.route("/api/chart_data")
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


@app.route("/api/login_history")
@api_login_required
def get_login_history():
    # Админ видит все входы, остальные — только свои
    q = LoginHistory.query
    if g.user.role != 'admin':
        q = q.filter_by(username=g.user.username)
    history = q.order_by(LoginHistory.timestamp.desc()).limit(10).all()
    return jsonify({"ok": True, "history": [{
        "username": h.username, "ip": h.ip_address or "Неизвестно",
        "success": h.success, "time": iso(h.timestamp),
    } for h in history]})


@app.route("/api/employees/export", methods=["GET"])
@api_login_required
def export_employees():
    emps = scoped_employees().order_by(Employee.id).all()
    si = StringIO()
    si.write('﻿')
    cw = csv.writer(si, delimiter=';')
    cw.writerow(["ID", "ФИО", "Логин", "Отдел", "Роль", "Дата создания"])
    roles = {"Sbis_Stager": "Стажер", "Sbis_Main": "Основной", "Sbis_Senior": "Старший"}
    for emp in emps:
        created = emp.created_at.strftime("%d.%m.%Y %H:%M") if emp.created_at else ""
        cw.writerow([emp.id, csv_safe(emp.full_name), csv_safe(emp.login), csv_safe(emp.department),
                     roles.get(emp.role, emp.role), created])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=employees_export.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output


# --- API: вход / выход ---
@app.route("/api/login", methods=["POST"])
def login():
    ip = client_ip()
    data = request.get_json(silent=True) or {}
    username = str(data.get("login") or "").strip()[:80]
    password = str(data.get("password") or "")

    wait = login_lock_seconds(ip, username)
    if wait:
        return jsonify({"ok": False, "seconds": wait,
                        "message": f"Заблокировано. Ждите {wait // 60} мин. {wait % 60} сек."}), 429

    user = User.query.filter_by(username=username).first() if username else None

    if user and user.check_password(password):
        session.clear()  # новая сессия после входа
        session['user_id'] = user.id
        session['csrf'] = secrets.token_hex(16)
        db.session.add(LoginHistory(username=username, ip_address=ip, success=True))
        db.session.commit()
        return jsonify({"ok": True, "role": user.role})

    db.session.add(LoginHistory(username=username, ip_address=ip, success=False))
    db.session.commit()

    wait = login_lock_seconds(ip, username)
    if wait:
        return jsonify({"ok": False, "seconds": wait,
                        "message": "Слишком много попыток. Вход заблокирован на 30 минут."}), 429

    left = LOCK_ATTEMPTS - LoginHistory.query.filter(
        LoginHistory.ip_address == ip, LoginHistory.username == username, LoginHistory.success.is_(False),
        LoginHistory.timestamp > datetime.utcnow() - LOCK_WINDOW).count()
    return jsonify({"ok": False, "message": f"Неверный логин или пароль. Осталось попыток: {max(left, 0)}"}), 401


@app.route("/api/check_lockout", methods=["GET"])
def check_lockout():
    wait = login_lock_seconds(client_ip(), (request.args.get('login') or '').strip()[:80] or None)
    return jsonify({"locked": bool(wait), "seconds": wait})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


# --- API: сотрудники ---
@app.route("/api/create", methods=["POST"])
@api_login_required
def create():
    data = request.get_json(silent=True) or {}
    full_name = " ".join(str(data.get("full_name") or "").split())
    login = str(data.get("login") or "").strip()
    email = str(data.get("email") or "").strip()
    password = str(data.get("password") or "")
    confirm = str(data.get("confirm") or "")
    department = data.get("department")
    selected_role = data.get("role", "Sbis_Stager")

    if not full_name or not login or not password or not department:
        return jsonify({"ok": False, "message": "Заполните все поля"}), 400
    if len(full_name) < 3 or len(full_name) > 150 or not NAME_RE.match(full_name):
        return jsonify({"ok": False, "message": "ФИО: от 3 до 150 символов, только буквы, пробелы, точки и дефисы"}), 400
    if not LOGIN_RE.match(login):
        return jsonify({"ok": False, "message": "Логин: от 3 до 20 символов (латиница, цифры, точки, дефисы)"}), 400
    if email and not EMAIL_RE.match(email):
        return jsonify({"ok": False, "message": "Некорректный email"}), 400
    if password != confirm:
        return jsonify({"ok": False, "message": "Пароли не совпадают"}), 400
    err = password_error(password)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    if department not in DEPARTMENTS:
        return jsonify({"ok": False, "message": "Неизвестный отдел"}), 400
    if selected_role not in EMPLOYEE_ROLES:
        return jsonify({"ok": False, "message": "Неизвестная роль"}), 400

    if g.user.role != 'admin' and department != g.user.department:
        return jsonify({"ok": False, "message": "Нет прав на этот отдел"}), 403
    if g.user.role != 'admin' and selected_role == 'Sbis_Senior':
        return jsonify({"ok": False, "message": "Только админ может создавать Старших"}), 403

    if Employee.query.filter(db.func.lower(Employee.login) == login.lower()).first():
        return jsonify({"ok": False, "message": "Сотрудник с таким логином уже есть"}), 409

    try:
        ok, message = create_user(full_name, login, password, department=department,
                                  group_dn=get_group_dn(selected_role), email=email or None)
    except Exception as e:
        traceback.print_exc()
        ok, message = False, f"Ошибка связи с AD: {e}"

    if ok:
        db.session.add(Employee(full_name=full_name, login=login, department=department, role=selected_role))
        text = f"создал сотрудника {full_name}"
        log_action(text)
        db.session.commit()
        notify_action(text)

        if SABY_ENABLED:
            # Saby не критичен: ошибка не отменяет создание в AD
            try:
                from saby_utils import create_saby_user
                saby_ok, saby_msg = create_saby_user(full_name, login, password, department)
            except Exception as e:
                traceback.print_exc()
                saby_ok, saby_msg = False, f"Ошибка Saby: {e}"
            message += f" | Saby: {saby_msg}"

    return jsonify({"ok": ok, "message": message}), (200 if ok else 500)


@app.route("/api/employees", methods=["GET"])
@api_login_required
def get_employees():
    emps = scoped_employees().order_by(Employee.full_name).all()
    return jsonify({"ok": True, "employees": [{
        "id": e.id, "full_name": e.full_name, "role": e.role,
        "department": e.department, "created_at": iso(e.created_at),
    } for e in emps]})


@app.route("/api/employee/<int:emp_id>/promote", methods=["POST"])
@api_roles_required('admin', 'manager')
def promote_employee(emp_id):
    emp = scoped_employees().filter(Employee.id == emp_id).first()
    if not emp:
        return jsonify({"ok": False, "message": "Не найден"}), 404
    if emp.role != "Sbis_Stager":
        return jsonify({"ok": False, "message": "Уже не стажер"}), 400

    if AD_SYNC_CHANGES:
        ok, message = change_group(emp.login, from_group_dn=get_group_dn("Sbis_Stager"), to_group_dn=get_group_dn("Sbis_Main"))
        if not ok:
            return jsonify({"ok": False, "message": message}), 500

    emp.role = "Sbis_Main"
    text = f"повысил сотрудника {emp.full_name}"
    log_action(text)
    db.session.commit()
    notify_action(text)
    return jsonify({"ok": True, "message": "Повышен"})


@app.route("/api/employee/<int:emp_id>", methods=["DELETE"])
@api_login_required
def delete_employee(emp_id):
    emp = scoped_employees().filter(Employee.id == emp_id).first()
    if not emp:
        return jsonify({"ok": False, "message": "Не найден"}), 404
    if g.user.role == 'hr' and emp.role != "Sbis_Stager":
        return jsonify({"ok": False, "message": "HR удаляет только стажеров"}), 403

    if AD_SYNC_CHANGES:
        ok, message = ad_delete_user(emp.login)
        if not ok:
            return jsonify({"ok": False, "message": message}), 500

    text = f"удалил сотрудника {emp.full_name}"
    log_action(text)
    db.session.delete(emp)
    db.session.commit()
    notify_action(text)
    return jsonify({"ok": True, "message": "Удален"})


# --- API: пользователи панели (только админ) ---
def serialize_user(u):
    return {"id": u.id, "username": u.username, "first_name": u.first_name, "role": u.role, "department": u.department}


@app.route("/api/users", methods=["GET"])
@api_roles_required('admin')
def list_users():
    return jsonify({"ok": True, "users": [serialize_user(u) for u in User.query.order_by(User.username).all()]})


@app.route("/api/users", methods=["POST"])
@api_roles_required('admin')
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
    if role != 'admin':
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
    return jsonify({"ok": True, "message": f"Пользователь {username} создан", "user": serialize_user(user)})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@api_roles_required('admin')
def delete_panel_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"ok": False, "message": "Не найден"}), 404
    if user.id == g.user.id:
        return jsonify({"ok": False, "message": "Нельзя удалить самого себя"}), 400
    log_action(f"удалил пользователя панели {user.username}")
    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True, "message": "Пользователь удалён"})


@app.route("/api/users/<int:user_id>/password", methods=["POST"])
@api_roles_required('admin')
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
    return jsonify({"ok": True, "message": f"Пароль для {user.username} изменён"})


# --- ПРОФИЛЬ ---
@app.route("/api/profile", methods=["GET"])
@api_login_required
def get_profile():
    return jsonify({"ok": True, "username": g.user.username, "first_name": g.user.first_name,
                    "avatar": g.user.avatar, "role": g.user.role, "department": g.user.department})


@app.route("/api/profile", methods=["POST"])
@api_login_required
def update_profile():
    new_name = str((request.get_json(silent=True) or {}).get("first_name") or "").strip()
    if not new_name:
        return jsonify({"ok": False, "message": "Имя не может быть пустым"}), 400
    if len(new_name) > 50:
        return jsonify({"ok": False, "message": "Имя слишком длинное (максимум 50 символов)"}), 400
    g.user.first_name = new_name
    db.session.commit()
    return jsonify({"ok": True, "message": "Имя успешно обновлено!"})


@app.route("/api/profile/password", methods=["POST"])
@api_login_required
def update_password():
    data = request.get_json(silent=True) or {}
    old_pass = str(data.get("old_password") or "")
    new_pass = str(data.get("new_password") or "")
    if not old_pass or not new_pass:
        return jsonify({"ok": False, "message": "Заполните все поля"}), 400
    if not g.user.check_password(old_pass):
        return jsonify({"ok": False, "message": "Неверный текущий пароль"}), 400
    err = password_error(new_pass)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    if new_pass == old_pass:
        return jsonify({"ok": False, "message": "Новый пароль совпадает со старым"}), 400
    g.user.set_password(new_pass)
    db.session.commit()
    return jsonify({"ok": True, "message": "Пароль успешно изменен!"})


@app.route("/api/profile/avatar", methods=["POST"])
@api_login_required
def upload_avatar():
    file = request.files.get('avatar')
    if not file or not file.filename:
        return jsonify({"ok": False, "message": "Файл не выбран"}), 400

    head = file.read(8)
    file.seek(0)
    if head.startswith(b'\x89PNG'):
        ext = 'png'
    elif head.startswith(b'\xff\xd8'):
        ext = 'jpg'
    else:
        return jsonify({"ok": False, "message": "Только JPG и PNG"}), 400

    upload_folder = os.path.join(app.root_path, 'static', 'avatars')
    os.makedirs(upload_folder, exist_ok=True)
    # Удаляем старый аватар с другим расширением
    for old_ext in ('png', 'jpg', 'jpeg'):
        old = os.path.join(upload_folder, f"user_{g.user.id}.{old_ext}")
        if old_ext != ext and os.path.exists(old):
            os.remove(old)
    filename = f"user_{g.user.id}.{ext}"
    file.save(os.path.join(upload_folder, filename))

    g.user.avatar = filename
    db.session.commit()
    return jsonify({"ok": True, "message": "Аватарка обновлена!", "filename": filename})


@app.route("/health")
def health_check():
    # Простой ответ, что сервер жив
    return jsonify({"status": "ok"}), 200


# --- ОШИБКИ ---
HTTP_MESSAGES = {
    401: "Вы не авторизованы",
    404: "Не найдено",
    405: "Метод не поддерживается",
    413: "Файл слишком большой (максимум 2 МБ)",
    415: "Неверный формат запроса",
}

@app.errorhandler(Exception)
def handle_exception(e):
    wants_json = request.path.startswith('/api/')
    if isinstance(e, HTTPException):
        if wants_json:
            return jsonify({"ok": False, "message": HTTP_MESSAGES.get(e.code, e.description)}), e.code
        if e.code == 404:
            return render_template('404.html'), 404
        return e
    traceback.print_exc()
    db.session.rollback()
    if wants_json:
        return jsonify({"ok": False, "message": "Внутренняя ошибка сервера"}), 500
    return render_template('500.html'), 500


# --- CLI ---
@app.cli.command("init-db")
@click.option("--demo", is_flag=True, help="Создать ещё и тестового HR (hr_out)")
def init_db(demo):
    """Создаёт таблицы и админа. Пароль берётся из INITIAL_ADMIN_PASSWORD или генерируется."""
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        password = os.environ.get("INITIAL_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        admin = User(username="admin", role="admin", first_name="Карим")
        admin.set_password(password)
        db.session.add(admin)
        print(f"Админ создан: admin / {password}")
    if demo and not User.query.filter_by(username="hr_out").first():
        password = secrets.token_urlsafe(12)
        hr = User(username="hr_out", role="hr", department="Отдел исходящих звонков", first_name="Анна")
        hr.set_password(password)
        db.session.add(hr)
        print(f"Тестовый HR создан: hr_out / {password}")
    db.session.commit()
    print("БД создана!")


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
