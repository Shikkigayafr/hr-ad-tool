from app import app
from models import db, User

with app.app_context():
    if not User.query.filter_by(username='admin').first():
        u = User(username='admin', role='admin')
        u.set_password('admin')
        db.session.add(u)
        db.session.commit()
        print('Создан: admin / admin')
    else:
        print('admin уже существует')
