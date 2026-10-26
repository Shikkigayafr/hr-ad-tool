from flask import Flask, render_template, request, jsonify, session, redirect, url_for, make_response
from ad_utils import create_user
from models import db, User, Employee, ActionLog
import traceback
import random
import time
import os
from datetime import datetime, timedelta
import csv
from io import StringIO
import json
from flask.json.provider import DefaultJSONProvider
from flask_socketio import SocketIO # <-- НОВОЕ
from apscheduler.schedulers.background import BackgroundScheduler
from backup_utils import backup_database

app = Flask(__name__)
app.secret_key = "super_secret_key_for_session"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hr.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- ФИКС КИРИЛЛИЦЫ В JSON ---
app.config['JSON_AS_ASCII'] = False
class CustomJSONProvider(DefaultJSONProvider):
    ensure_ascii = False
app.json = CustomJSONProvider(app)

app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False 
app.config['SESSION_COOKIE_HTTPONLY'] = True

db.init_app(app)

# Инициализация SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# --- НАСТРОЙКА БЭКАПОВ ---
def start_backup_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=backup_database, 
        trigger="cron", 
        hour=3, 
        minute=0, 
        args=[app]
    )
    scheduler.start()
    print("✅ Планировщик бэкапов запущен (каждый день в 03:00)")

# Запускаем его только в production (чтобы не дублировалось при debug=True)
if os.environ.get('FLASK_ENV') == 'production' or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    start_backup_scheduler(app)
# --------------------------

# --- СТРАНИЦЫ ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/create")
def page_create():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template("create.html")

@app.route("/employees")
def page_employees():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template("employees.html")

@app.route("/profile")
def page_profile():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template("profile.html")

# --- API ---
@app.route("/api/me")
def api_me():
    if 'user_id' in session:
        return jsonify({"ok": True, "role": session.get('role')})
    return jsonify({"ok": False}), 401

@app.route("/api/stats")
def api_stats():
    if not session.get('user_id'): return jsonify({"ok": False}), 401
    
    current_user = User.query.get(session['user_id'])
    if current_user:
        display_name = current_user.first_name if current_user.first_name else current_user.username.capitalize()
        user_avatar = current_user.avatar
    else:
        display_name = 'Пользователь'
        user_avatar = None
        
    emps = Employee.query.all()
    total = len(emps)
    
    if total == 0:
        return jsonify({"ok": True, "total": 0, "online": 0, "employees": [], "user_name": display_name, "user_avatar": user_avatar})
    
    online_count = max(1, int(total * 0.3)) if total > 0 else 0
    random.shuffle(emps)
    
    employees_list = []
    for i, emp in enumerate(emps):
        is_online = i < online_count
        if is_online: last_seen = "Сейчас в сети"
        else:
            hours_ago = random.randint(1, 168) 
            last_seen = f"{hours_ago} ч. назад" if hours_ago < 24 else f"{hours_ago // 24} дн. назад"
        
        employees_list.append({
            "id": emp.id, "full_name": emp.full_name, "role": emp.role,
            "department": emp.department, "is_online": is_online, "last_seen": last_seen
        })
        
    employees_list.sort(key=lambda x: not x["is_online"])
    return jsonify({"ok": True, "total": total, "online": online_count, "employees": employees_list, "user_name": display_name, "user_avatar": user_avatar})

@app.route("/api/logs")
def get_logs():
    if not session.get('user_id'): return jsonify({"ok": False}), 401
    
    current_role = session.get('role')
    current_dep = session.get('department')
    
    if current_role == 'admin':
        logs = ActionLog.query.order_by(ActionLog.timestamp.desc()).limit(10).all()
    elif current_role == 'hr':
        logs = ActionLog.query.filter_by(user_role='hr').order_by(ActionLog.timestamp.desc()).limit(10).all()
    elif current_role == 'manager':
        logs = ActionLog.query.filter_by(department=current_dep).order_by(ActionLog.timestamp.desc()).limit(10).all()
    else:
        logs = []

    result = []
    now = datetime.utcnow()
    
    for log in logs:
        diff = now - log.timestamp
        minutes = int(diff.total_seconds() // 60)
        
        if minutes < 1: time_str = "только что"
        elif minutes < 60: time_str = f"{minutes} мин. назад"
        elif minutes < 1440: time_str = f"{minutes // 60} ч. назад"
        else: time_str = f"{minutes // 1440} дн. назад"
            
        result.append({"user": log.user_name, "action": log.action, "time": time_str})
        
    return jsonify({"ok": True, "logs": result})

@app.route("/api/chart_data")
def api_chart_data():
    if not session.get('user_id'): return jsonify({"ok": False}), 401
    days, counts = [], []
    for i in range(6, -1, -1):
        date = datetime.utcnow().date() - timedelta(days=i)
        days.append(date.strftime("%d.%m"))
        start_of_day = datetime.combine(date, datetime.min.time())
        end_of_day = datetime.combine(date, datetime.max.time())
        count = Employee.query.filter(Employee.created_at >= start_of_day, Employee.created_at <= end_of_day).count()
        counts.append(count)
    return jsonify({"ok": True, "labels": days, "data": counts})

@app.route("/api/employees/export", methods=["GET"])
def export_employees():
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    emps = Employee.query.all()
    si = StringIO()
    si.write('\ufeff') 
    cw = csv.writer(si, delimiter=';')
    cw.writerow(["ID", "ФИО", "Логин", "Отдел", "Роль", "Дата создания"])
    for emp in emps:
        role_rus = {"Sbis_Stager": "Стажер", "Sbis_Main": "Основной", "Sbis_Senior": "Старший"}.get(emp.role, emp.role)
        created = emp.created_at.strftime("%d.%m.%Y %H:%M") if emp.created_at else ""
        cw.writerow([emp.id, emp.full_name, emp.login, emp.department, role_rus, created])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=employees_export.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

@app.route("/api/login", methods=["POST"])
def login():
    lockout_until = session.get('lockout_until', 0)
    now = time.time()
    
    if now < lockout_until:
        wait_seconds = int(lockout_until - now)
        return jsonify({"ok": False, "message": f"Заблокировано. Ждите {wait_seconds // 60} мин. {wait_seconds % 60} сек."}), 429

    data = request.json or {}
    username = data.get("login")
    password = data.get("password")

    user = User.query.filter_by(username=username).first()
    
    if user and user.check_password(password):
        session.pop('login_attempts', None)
        session.pop('lockout_until', None)
        session['user_id'] = user.id
        session['role'] = user.role
        session['department'] = user.department
        session['username'] = user.username
        session['first_name'] = user.first_name
        return jsonify({"ok": True, "role": user.role})
    
    attempts = session.get('login_attempts', 0) + 1
    session['login_attempts'] = attempts

    if attempts >= 5:
        session['lockout_until'] = now + 1800
        return jsonify({"ok": False, "message": "Слишком много попыток. Вход заблокирован на 30 минут."}), 429

    return jsonify({"ok": False, "message": f"Неверный логин или пароль. Осталось попыток: {5 - attempts}"}), 401

@app.route("/api/check_lockout", methods=["GET"])
def check_lockout():
    lockout_until = session.get('lockout_until', 0)
    now = time.time()
    if now < lockout_until:
        return jsonify({"locked": True, "seconds": int(lockout_until - now)})
    return jsonify({"locked": False})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/create", methods=["POST"])
def create():
    if 'user_id' not in session: return jsonify({"ok": False, "message": "Вы не авторизованы"}), 401

    data = request.json or {}
    full_name = (data.get("full_name") or "").strip()
    login = (data.get("login") or "").strip()
    password = data.get("password") or ""
    confirm = data.get("confirm") or ""
    department = data.get("department")
    selected_role = data.get("role", "Sbis_Stager")

    if not full_name or not login or not password or not department: return jsonify({"ok": False, "message": "Заполните все поля"}), 400
    if password != confirm: return jsonify({"ok": False, "message": "Пароли не совпадают"}), 400

    current_role = session.get('role')
    current_dep = session.get('department')

    if current_role != 'admin' and department != current_dep: return jsonify({"ok": False, "message": "Нет прав на этот отдел"}), 403
    if current_role != 'admin' and selected_role == 'Sbis_Senior': return jsonify({"ok": False, "message": "Только админ может создавать Старших"}), 403

    group_dn = f"CN={selected_role},OU=Groups,DC=corp,DC=local" 
    try:
        ok, message = create_user(full_name, login, password, department=department, group_dn=group_dn)
    except Exception as e:
        ok, message = False, f"Ошибка сервера: {str(e)}"

    if ok:
        new_emp = Employee(full_name=full_name, login=login, department=department, role=selected_role)
        db.session.add(new_emp)
        
        actor_name = session.get('first_name') or session.get('username') or "Пользователь"
        actor_role = session.get('role')
        actor_dep = session.get('department')
        log_entry = ActionLog(user_name=actor_name, user_role=actor_role, department=actor_dep, action=f"создал сотрудника {full_name}")
        db.session.add(log_entry)
        
        db.session.commit()

        socketio.emit('new_log', {
            'user': actor_name, 
            'action': f"создал сотрудника {full_name}",
            'role': actor_role
        })

    return jsonify({"ok": ok, "message": message}), (200 if ok else 500)

@app.route("/api/employees", methods=["GET"])
def get_employees():
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    emps = Employee.query.all()
    result = [{"id": e.id, "full_name": e.full_name, "role": e.role} for e in emps]
    return jsonify({"ok": True, "employees": result})

@app.route("/api/employee/<int:emp_id>/promote", methods=["POST"])
def promote_employee(emp_id):
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    emp = Employee.query.get(emp_id)
    if not emp: return jsonify({"ok": False, "message": "Не найден"}), 404
    if session.get('role') == 'hr': return jsonify({"ok": False, "message": "Нет прав"}), 403
        
    if emp.role == "Sbis_Stager":
        emp.role = "Sbis_Main"
        
        actor_name = session.get('first_name') or session.get('username') or "Пользователь"
        actor_role = session.get('role')
        actor_dep = session.get('department')
        db.session.add(ActionLog(user_name=actor_name, user_role=actor_role, department=actor_dep, action=f"повысил сотрудника {emp.full_name}"))
        
        db.session.commit()

        socketio.emit('new_log', {
            'user': actor_name, 
            'action': f"повысил сотрудника {emp.full_name}",
            'role': actor_role
        })

        return jsonify({"ok": True, "message": "Повышен"})
    return jsonify({"ok": False, "message": "Уже не стажер"})

@app.route("/api/employee/<int:emp_id>", methods=["DELETE"])
def delete_employee(emp_id):
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    emp = Employee.query.get(emp_id)
    if not emp: return jsonify({"ok": False}), 404
    if session.get('role') == 'hr' and emp.role != "Sbis_Stager": return jsonify({"ok": False, "message": "HR удаляет только стажеров"}), 403

    actor_name = session.get('first_name') or session.get('username') or "Пользователь"
    actor_role = session.get('role')
    actor_dep = session.get('department')
    db.session.add(ActionLog(user_name=actor_name, user_role=actor_role, department=actor_dep, action=f"удалил сотрудника {emp.full_name}"))
    
    db.session.delete(emp)
    db.session.commit()

    socketio.emit('new_log', {
        'user': actor_name, 
        'action': f"удалил сотрудника {emp.full_name}",
        'role': actor_role
    })

    return jsonify({"ok": True, "message": "Удален"})

# --- ПРОФИЛЬ ---
@app.route("/api/profile", methods=["GET"])
def get_profile():
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    user = User.query.get(session['user_id'])
    return jsonify({"ok": True, "username": user.username, "first_name": user.first_name, "avatar": user.avatar})

@app.route("/api/profile", methods=["POST"])
def update_profile():
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    data = request.json or {}
    new_name = (data.get("first_name") or "").strip()
    if not new_name: return jsonify({"ok": False, "message": "Имя не может быть пустым"}), 400
    user = User.query.get(session['user_id'])
    user.first_name = new_name
    db.session.commit()
    session['first_name'] = new_name
    return jsonify({"ok": True, "message": "Имя успешно обновлено!"})

@app.route("/api/profile/password", methods=["POST"])
def update_password():
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    data = request.json or {}
    old_pass = data.get("old_password")
    new_pass = data.get("new_password")
    user = User.query.get(session['user_id'])
    if not user.check_password(old_pass): return jsonify({"ok": False, "message": "Неверный текущий пароль"}), 400
    user.set_password(new_pass)
    db.session.commit()
    return jsonify({"ok": True, "message": "Пароль успешно изменен!"})

@app.route("/api/profile/avatar", methods=["POST"])
def upload_avatar():
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    if 'avatar' not in request.files: return jsonify({"ok": False, "message": "Файл не выбран"}), 400
    file = request.files['avatar']
    if file.filename == '': return jsonify({"ok": False, "message": "Файл не выбран"}), 400
        
    if file and file.filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg'}:
        upload_folder = os.path.join(app.root_path, 'static', 'avatars')
        os.makedirs(upload_folder, exist_ok=True)
        filename = f"user_{session['user_id']}.{file.filename.rsplit('.', 1)[1].lower()}"
        file.save(os.path.join(upload_folder, filename))
        
        user = User.query.get(session['user_id'])
        user.avatar = filename
        db.session.commit()
        return jsonify({"ok": True, "message": "Аватарка обновлена!", "filename": filename})
    return jsonify({"ok": False, "message": "Только JPG и PNG"}), 400

@app.route("/health")
def health_check():
    # Простой ответ, что сервер жив
    return jsonify({"status": "ok"}), 200

@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    if request.path.startswith('/api/'):
        return jsonify({"ok": False, "message": str(e)}), 500
    return render_template('500.html'), 500

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

@app.cli.command("init-db")
def init_db():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", role="admin", first_name="Карим")
        admin.set_password("admin123")
        db.session.add(admin)
    if not User.query.filter_by(username="hr_out").first():
        hr = User(username="hr_out", role="hr", department="Отдел исходящих звонков", first_name="Анна")
        hr.set_password("hr12345")
        db.session.add(hr)
    db.session.commit()
    print("БД создана!")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)