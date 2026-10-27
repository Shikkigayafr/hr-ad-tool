import os
import sys

# Окружение задаём ДО импорта app: тестовая БД в памяти, AD только имитируется
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DRY_RUN"] = "true"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["SABY_ENABLED"] = "false"
os.environ["AD_SYNC_CHANGES"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask.testing import FlaskClient

from app import app as flask_app
from models import db, User

PASSWORD = "Passw0rd!x"
DEPT_A = "Офис"
DEPT_B = "Колл Центр"


class CsrfClient(FlaskClient):
    """Тестовый клиент: как браузер, сам добавляет X-CSRF-Token к изменяющим запросам."""

    def open(self, *args, **kwargs):
        if kwargs.get("method", "GET").upper() not in ("GET", "HEAD", "OPTIONS") and not kwargs.pop("no_csrf", False):
            with self.session_transaction() as sess:
                token = sess.get("csrf")
            if token:
                # явно переданный заголовок (например, неверный токен в тесте) не перезаписываем
                kwargs["headers"] = {"X-CSRF-Token": token, **dict(kwargs.get("headers") or {})}
        kwargs.pop("no_csrf", None)
        return super().open(*args, **kwargs)


@pytest.fixture
def app():
    flask_app.config["TESTING"] = True
    flask_app.test_client_class = CsrfClient
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        for username, role, dept in [
            ("admin", "admin", None),
            ("hr_a", "hr", DEPT_A),
            ("hr_b", "hr", DEPT_B),
            ("mgr_a", "manager", DEPT_A),
        ]:
            user = User(username=username, role=role, department=dept, first_name=username)
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()
        yield flask_app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username, password=PASSWORD):
    return client.post("/api/login", json={"login": username, "password": password})


@pytest.fixture
def as_user(app):
    """as_user('hr_a') -> клиент, уже вошедший под этим пользователем."""
    def make(username):
        c = app.test_client()
        assert login(c, username).status_code == 200
        return c
    return make


def employee_payload(login_name="ivanov.ii", department=DEPT_A, role="Sbis_Stager", **extra):
    data = {
        "full_name": "Иванов Иван Иванович", "login": login_name, "email": "ivanov@evostor.ru",
        "password": PASSWORD, "confirm": PASSWORD, "department": department, "role": role,
    }
    data.update(extra)
    return data
