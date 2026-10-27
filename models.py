from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # scrypt-хеш ~160 символов; PostgreSQL длину проверяет
    first_name = db.Column(db.String(50), nullable=True)
    avatar = db.Column(db.String(200), nullable=True)
    
    role = db.Column(db.String(20), nullable=False, default='hr') 
    department = db.Column(db.String(100), nullable=True) 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    login = db.Column(db.String(80), unique=True, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (db.Index('ix_employee_department', 'department'),)

class ActionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100), nullable=False) 
    user_role = db.Column(db.String(20), nullable=False)  # РОЛЬ ТОГО, КТО СДЕЛАЛ
    department = db.Column(db.String(100), nullable=True) # ОТДЕЛ ТОГО, КТО СДЕЛАЛ
    action = db.Column(db.String(200), nullable=False)    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (db.Index('ix_action_log_department', 'department'),)

class LoginHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False) # Кто пытался войти
    ip_address = db.Column(db.String(50), nullable=True) # С какого IP
    success = db.Column(db.Boolean, default=False) # Успешно или нет
    timestamp = db.Column(db.DateTime, default=datetime.utcnow) # Когда

    # Блокировка входа считает неудачные попытки по (ip, username, время)
    __table_args__ = (db.Index('ix_login_history_lookup', 'ip_address', 'username', 'timestamp'),)