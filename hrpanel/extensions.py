"""Расширения Flask создаются здесь один раз и подключаются к приложению в create_app()."""
import os

from flask_migrate import Migrate
from flask_socketio import SocketIO

from hrpanel.config import BASE_DIR
from models import db

socketio = SocketIO()
# render_as_batch нужен, чтобы миграции работали и на SQLite (ALTER TABLE), и на PostgreSQL
migrate = Migrate(directory=os.path.join(BASE_DIR, "migrations"), render_as_batch=True)

__all__ = ["db", "socketio", "migrate"]
