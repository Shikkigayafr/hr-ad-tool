"""Настройки приложения: всё берётся из окружения (.env / Docker secrets)."""
import logging
import os
import secrets

from sqlalchemy.engine import URL

from secret_utils import read_secret

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("hrpanel")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def database_uri() -> str:
    """DATABASE_URL, либо PostgreSQL из частей (POSTGRES_*; пароль может быть Docker secret),
    либо SQLite в instance/hr.db для локальной разработки."""
    url = os.environ.get("DATABASE_URL")
    if url:
        # postgres:// и postgresql:// без драйвера SQLAlchemy 2.1 открывает через psycopg (v3),
        # а в зависимостях psycopg2 — указываем драйвер явно
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg2://" + url[len(prefix):]
        return url

    host = os.environ.get("POSTGRES_HOST")
    if host:
        return URL.create(
            "postgresql+psycopg2",
            username=os.environ.get("POSTGRES_USER", "hrpanel"),
            password=read_secret("POSTGRES_PASSWORD", ""),
            host=host,
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            database=os.environ.get("POSTGRES_DB", "hrpanel"),
        ).render_as_string(hide_password=False)

    return "sqlite:///hr.db"


def apply_config(app, overrides: dict | None = None) -> None:
    secret_key = read_secret("SECRET_KEY")
    if not secret_key:
        # Без SECRET_KEY сессии живут только до перезапуска. Задайте его в .env или secrets!
        log.warning("SECRET_KEY не задан — сгенерирован временный ключ, сессии сбросятся при перезапуске")
        secret_key = secrets.token_hex(32)

    app.config.update(
        SECRET_KEY=secret_key,
        SQLALCHEMY_DATABASE_URI=database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # аватарки не больше 2 МБ
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=env_bool("SESSION_COOKIE_SECURE"),  # true — если панель открывается по HTTPS
        SESSION_COOKIE_HTTPONLY=True,
        # Флаги интеграций (по умолчанию выключены — безопасно для разработки без AD/Saby)
        SABY_ENABLED=env_bool("SABY_ENABLED"),
        YANDEX_ENABLED=env_bool("YANDEX_ENABLED"),
        AD_SYNC_CHANGES=env_bool("AD_SYNC_CHANGES"),
        TRUST_PROXY=env_bool("TRUST_PROXY"),
        # /metrics отдаётся только с этим токеном (Authorization: Bearer ...). Пусто — эндпоинт отключён (404)
        METRICS_TOKEN=read_secret("METRICS_TOKEN") or "",
        APP_VERSION=os.environ.get("APP_VERSION", "dev"),
        # Socket.IO: по умолчанию только свой origin; другие — через запятую
        CORS_ORIGINS=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
    )
    if overrides:
        app.config.update(overrides)
