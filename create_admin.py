import getpass

from app import app
from hrpanel.validators import password_error
from models import db, User

with app.app_context():
    if User.query.filter_by(username='admin').first():
        print('admin уже существует')
    else:
        password = getpass.getpass('Пароль для admin: ')
        error = password_error(password)
        if error:
            print(error)
        else:
            u = User(username='admin', role='admin')
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            print('Создан: admin')
