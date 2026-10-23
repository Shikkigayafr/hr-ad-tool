from app import app
from models import User

with app.app_context():
    u = User.query.filter_by(username='admin').first()
    if not u:
        print('Нет пользователя admin')
    else:
        for pwd in ['admin', 'admin123', 'password', '123456', 'adminadmin']:
            if u.check_password(pwd):
                print(f'ПАРОЛЬ НАЙДЕН: {pwd}')
                break
        else:
            print('Стандартные пароли не подошли')
            print('Хеш:', u.password_hash[:40], '...')
