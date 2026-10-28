"""Структурированные JSON-логи: stdout (для Docker) + файл с ротацией.

Каждая строка — один JSON-объект, его удобно скармливать Loki/ELK и грепать через jq.
Пароли и тела запросов в логи не попадают.
"""
import json
import logging
import logging.handlers
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

from flask import g, request

from hrpanel.config import BASE_DIR, env_bool

SKIP_REQUEST_LOG = {"static", "system.health_check", "system.metrics"}
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        data.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def setup_logging(app) -> None:
    logger = logging.getLogger("hrpanel")
    if getattr(logger, "_hrpanel_configured", False):
        return
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

    formatter = JsonFormatter()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if env_bool("LOG_TO_FILE", True):
        log_dir = os.environ.get("LOG_DIR", os.path.join(BASE_DIR, "logs"))
        try:
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                os.path.join(log_dir, "app.log"),
                maxBytes=int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024)),
                backupCount=int(os.environ.get("LOG_BACKUP_COUNT", 5)),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:  # нет прав на запись — работаем только в stdout
            logger.warning("Файловый лог отключён: %s", exc)

    logger._hrpanel_configured = True


def audit(event: str, **fields) -> None:
    """Событие безопасности/действие пользователя: вход, создание, сброс пароля и т.д."""
    actor = {}
    try:
        user = getattr(g, "user", None)
        if user:
            actor = {"actor": user.username, "actor_role": user.role}
        if getattr(g, "request_id", None):
            actor["request_id"] = g.request_id
    except RuntimeError:  # вне запроса
        pass
    logging.getLogger("hrpanel.audit").info(event, extra={"fields": {"event": event, **actor, **fields}})
    from hrpanel.metrics import AUDIT_EVENTS  # импорт здесь: metrics не должен зависеть от логирования
    AUDIT_EVENTS.labels(event).inc()


def register_request_logging(app) -> None:
    request_logger = logging.getLogger("hrpanel.request")

    @app.before_request
    def start_request():
        incoming = request.headers.get("X-Request-ID", "")
        g.request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex[:12]
        g.started = time.perf_counter()

    @app.after_request
    def log_request(response):
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers["X-Request-ID"] = request_id
        if request.endpoint in SKIP_REQUEST_LOG:
            return response

        from hrpanel.security import client_ip  # импорт здесь: security тоже использует логирование

        user = getattr(g, "user", None)
        request_logger.info("request", extra={"fields": {
            "request_id": request_id,
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - getattr(g, "started", time.perf_counter())) * 1000, 1),
            "ip": client_ip(),
            "user": user.username if user else None,
        }})
        return response
