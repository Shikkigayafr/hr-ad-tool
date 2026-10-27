"""Команды flask: применение миграций и создание первого админа."""
import os
import secrets

import click
from flask_migrate import stamp, upgrade
from sqlalchemy import inspect

from hrpanel.extensions import db
from models import User

# Миграция, соответствующая схеме, которую создавал старый db.create_all()
BASELINE_REVISION = "0001"


def run_migrations():
    """Идемпотентно приводит БД к актуальной схеме. Базу, созданную до появления
    миграций (есть таблицы, но нет alembic_version), сначала помечает как baseline."""
    tables = set(inspect(db.engine).get_table_names())
    if "alembic_version" not in tables and "user" in tables:
        stamp(revision=BASELINE_REVISION)
    upgrade()


def register_cli(app):
    @app.cli.command("upgrade-db")
    def upgrade_db():
        """Применяет миграции БД (безопасно запускать при каждом старте)."""
        run_migrations()
        print("Схема БД актуальна")

    @app.cli.command("init-db")
    @click.option("--demo", is_flag=True, help="Создать ещё и тестового HR (hr_out)")
    def init_db(demo):
        """Применяет миграции и создаёт админа. Пароль: INITIAL_ADMIN_PASSWORD или генерируется."""
        run_migrations()
        if not User.query.filter_by(username="admin").first():
            from secret_utils import read_secret
            password = read_secret("INITIAL_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
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
        print("БД готова!")
