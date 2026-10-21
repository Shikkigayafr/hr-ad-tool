from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from ad_utils import create_user
from models import db, User, Employee
import traceback

app = Flask(__name__)
app.secret_key = "super_secret_key_for_session"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hr.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- ФИКС СЕССИИ ---
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False 
app.config['SESSION_COOKIE_HTTPONLY'] = True

db.init_app(app)

# --- СТРАНИЦЫ ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/create")
def page_create():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template("create.html")

@app.route("/employees")
def page_employees():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template("employees.html")

# --- API ---
@app.route("/api/me")
def api_me():
    if 'user_id' in session:
        return jsonify({"ok": True, "role": session.get('role')})
    return jsonify({"ok": False}), 401

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("login")
    password = data.get("password")

    user = User.query.filter_by(username=username).first()
    
    if user and user.check_password(password):
        session['user_id'] = user.id
        session['role'] = user.role
        session['department'] = user.department
        return jsonify({"ok": True, "role": user.role})
    
    return jsonify({"ok": False, "message": "Неверный логин или пароль"}), 401

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/create", methods=["POST"])
def create():
    if 'user_id' not in session:
        return jsonify({"ok": False, "message": "Вы не авторизованы"}), 401

    data = request.json or {}
    full_name = (data.get("full_name") or "").strip()
    login = (data.get("login") or "").strip()
    password = data.get("password") or ""
    confirm = data.get("confirm") or ""
    department = data.get("department")
    selected_role = data.get("role", "Sbis_Stager")

    if not full_name or not login or not password or not department:
        return jsonify({"ok": False, "message": "Заполните все поля"}), 400
    if password != confirm:
        return jsonify({"ok": False, "message": "Пароли не совпадают"}), 400

    current_role = session.get('role')
    current_dep = session.get('department')

    if current_role != 'admin' and department != current_dep:
         return jsonify({"ok": False, "message": "Нет прав на этот отдел"}), 403
         
    if current_role != 'admin' and selected_role == 'Sbis_Senior':
        return jsonify({"ok": False, "message": "Только админ может создавать Старших"}), 403

    # ВАЖНО: Передаем department в функцию!
    group_dn = f"CN={selected_role},OU=Groups,DC=corp,DC=local" 
    ok, message = create_user(full_name, login, password, department=department, group_dn=group_dn)

    if ok:
        new_emp = Employee(full_name=full_name, login=login, department=department, role=selected_role)
        db.session.add(new_emp)
        db.session.commit()

    return jsonify({"ok": ok, "message": message}), (200 if ok else 500)

# ... (остальные маршруты /api/employees, /api/employee/.../promote, DELETE, init_db остаются без изменений) ...

@app.route("/api/employees", methods=["GET"])
def get_employees():
    if 'user_id' not in session:
        return jsonify({"ok": False}), 401
    
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
        db.session.commit()
        return jsonify({"ok": True, "message": "Повышен"})
    return jsonify({"ok": False, "message": "Уже не стажер"})

@app.route("/api/employee/<int:emp_id>", methods=["DELETE"])
def delete_employee(emp_id):
    if 'user_id' not in session: return jsonify({"ok": False}), 401
    emp = Employee.query.get(emp_id)
    if not emp: return jsonify({"ok": False}), 404
    if session.get('role') == 'hr' and emp.role != "Sbis_Stager":
        return jsonify({"ok": False, "message": "HR удаляет только стажеров"}), 403

    db.session.delete(emp)
    db.session.commit()
    return jsonify({"ok": True, "message": "Удален"})

@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    return jsonify({"ok": False, "message": str(e)}), 500

@app.cli.command("init-db")
def init_db():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", role="admin")
        admin.set_password("admin123")
        db.session.add(admin)
    if not User.query.filter_by(username="hr_out").first():
        hr = User(username="hr_out", role="hr", department="Отдел исходящих звонков")
        hr.set_password("hr12345")
        db.session.add(hr)
    db.session.commit()
    print("БД создана!")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)