from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False) # Логин для входа на сайт
    password_hash = db.Column(db.String(128), nullable=False)        # Хеш пароля
    
    # Права доступа: 'admin' (всё может), 'hr' (создает стажеров), 'manager' (смотрит только свой отдел)
    role = db.Column(db.String(20), nullable=False, default='hr') 
    
    # К какому отделу привязан (например, "Отдел исходящих звонков")
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
    role = db.Column(db.String(50), nullable=False) # Sbis_Stager или Sbis_Main