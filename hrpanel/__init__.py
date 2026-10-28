"""HR → AD панель: фабрика приложения.

Структура:
  config.py          настройки из окружения / Docker secrets
  logging_config.py  JSON-логи, аудит, логирование запросов
  security.py        сессии, CSRF, блокировка входа, декораторы прав
  services.py        журнал действий, оповещения, выборки по правам
  validators.py      проверки данных, генератор паролей
  blueprints/        маршруты: pages, auth, dashboard, employees, panel_users, profile, system
  sockets.py         Socket.IO; errors.py — обработчики ошибок; cli.py — команды flask
"""
import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from flask.json.provider import DefaultJSONProvider

from hrpanel.config import BASE_DIR, apply_config
from hrpanel.extensions import db, migrate, socketio


class CustomJSONProvider(DefaultJSONProvider):
    ensure_ascii = False  # кириллица в JSON без \uXXXX


def start_backup_scheduler(app):
    from backup_utils import backup_database

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=backup_database, trigger="cron", hour=3, minute=0, args=[app])
    scheduler.start()
    logging.getLogger("hrpanel").info("Планировщик бэкапов запущен (каждый день в 03:00)")


def create_app(config_overrides: dict | None = None) -> Flask:
    # root_path = корень проекта: оттуда берутся templates/, static/, instance/
    app = Flask(__name__, root_path=BASE_DIR, instance_path=os.path.join(BASE_DIR, "instance"))
    app.json = CustomJSONProvider(app)
    apply_config(app, config_overrides)

    from hrpanel.logging_config import register_request_logging, setup_logging
    setup_logging(app)
    register_request_logging(app)  # первым: задаёт request_id для остальных хуков

    from hrpanel.metrics import register_metrics
    register_metrics(app)

    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins=app.config["CORS_ORIGINS"] or None)

    from hrpanel.security import register_security
    register_security(app)

    from hrpanel.blueprints import register_blueprints
    register_blueprints(app)

    from hrpanel import sockets  # noqa: F401  (регистрирует обработчики Socket.IO)
    from hrpanel.errors import register_error_handlers
    register_error_handlers(app)

    from hrpanel.cli import register_cli
    register_cli(app)

    # Бэкапы SQLite — только в production (чтобы не дублировалось при debug-перезапуске)
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_backup_scheduler(app)

    return app
