"""Метрики в формате Prometheus (их читают и Prometheus/Grafana, и Zabbix 6.0+ через HTTP-агент).

Три группы метрик:
  * приложение — запросы (число, статусы, время), события аудита (входы, создания, сбросы паролей), WebSocket-клиенты;
  * интеграции — вызовы AD и Saby: сколько, с каким результатом, как долго, когда был последний успех;
  * бизнес и состояние — сотрудники по отделам/ролям/статусам, пользователи панели, неудачные входы, доступность БД.
    Эти значения читаются из БД в момент опроса, поэтому не обнуляются при перезапуске приложения.

Метрик с высокой кардинальностью (логины, ФИО, пути с id) здесь нет намеренно.
"""
import logging
import time
from datetime import datetime, timedelta

from flask import g, request
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.gc_collector import GCCollector
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector

log = logging.getLogger("hrpanel")

REGISTRY = CollectorRegistry()
ProcessCollector(registry=REGISTRY)    # CPU, память, дескрипторы процесса (Linux)
PlatformCollector(registry=REGISTRY)   # версия Python
GCCollector(registry=REGISTRY)

SKIP_ENDPOINTS = {"static", "system.health_check", "system.metrics"}
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

# --- Приложение ---
HTTP_REQUESTS = Counter("hrpanel_http_requests_total", "HTTP-запросы по эндпоинтам Flask и статусам",
                        ["method", "endpoint", "status"], registry=REGISTRY)
HTTP_DURATION = Histogram("hrpanel_http_request_duration_seconds", "Время обработки запроса",
                          ["endpoint"], buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10), registry=REGISTRY)
# Счётчики без меток существуют всегда (даже со значением 0): на них опираются Zabbix-элементы и оповещения,
# которым нужна серия «с самого начала», а не после первой ошибки
HTTP_HANDLED = Counter("hrpanel_http_requests_handled", "Все обработанные HTTP-запросы (без /health и /metrics)", registry=REGISTRY)
HTTP_SERVER_ERRORS = Counter("hrpanel_http_server_errors", "Ответы со статусом 5xx", registry=REGISTRY)
HTTP_IN_PROGRESS = Gauge("hrpanel_http_requests_in_progress", "Запросы, обрабатываемые прямо сейчас", registry=REGISTRY)

AUDIT_EVENTS = Counter("hrpanel_audit_events_total", "События аудита (входы, создание, отключение, сброс пароля…)",
                       ["event"], registry=REGISTRY)
KNOWN_AUDIT_EVENTS = (
    "login_success", "login_failed", "login_blocked", "login_locked",
    "employee_created", "employee_create_failed", "employees_imported", "employee_promoted",
    "employee_disabled", "employee_enabled", "employee_deleted",
    "password_reset", "password_reset_failed", "password_changed",
    "panel_user_created", "panel_user_deleted", "panel_user_password_reset", "saby_create",
)

WS_CLIENTS = Gauge("hrpanel_websocket_clients", "Подключённые WebSocket-клиенты (вкладки с лентой событий)", registry=REGISTRY)
APP_INFO = Gauge("hrpanel_info", "Информация о сборке (значение всегда 1)", ["version", "database"], registry=REGISTRY)
FEATURE_FLAGS = Gauge("hrpanel_feature_flag", "Флаги интеграций: 1 — включён", ["flag"], registry=REGISTRY)

# --- Интеграции ---
AD_OPS = Counter("hrpanel_ad_operations_total", "Операции с AD по результату (ok / fail — отказ AD / error — нет связи)",
                 ["operation", "result"], registry=REGISTRY)
AD_DURATION = Histogram("hrpanel_ad_operation_duration_seconds", "Время операции с AD", ["operation"],
                        buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30), registry=REGISTRY)
AD_LAST_SUCCESS = Gauge("hrpanel_ad_last_success_timestamp_seconds", "Unix-время последней успешной операции с AD",
                        ["operation"], registry=REGISTRY)
SABY_OPS = Counter("hrpanel_saby_operations_total", "Операции с Saby по результату", ["operation", "result"], registry=REGISTRY)
SABY_DURATION = Histogram("hrpanel_saby_operation_duration_seconds", "Время операции с Saby", ["operation"],
                          buckets=(0.25, 0.5, 1, 2.5, 5, 10, 30, 60), registry=REGISTRY)
SABY_LAST_SUCCESS = Gauge("hrpanel_saby_last_success_timestamp_seconds", "Unix-время последней успешной операции с Saby",
                          ["operation"], registry=REGISTRY)

AD_OPERATIONS = ("create_user", "change_group", "disable_user", "enable_user", "delete_user", "reset_password")
SABY_OPERATIONS = ("create_user",)
RESULTS = ("ok", "fail", "error")


def _prime_series():
    """Создаёт нулевые серии заранее: rate()/Zabbix видят метрику до первого события."""
    for event in KNOWN_AUDIT_EVENTS:
        AUDIT_EVENTS.labels(event)
    for operation in AD_OPERATIONS:
        for result in RESULTS:
            AD_OPS.labels(operation, result)
    for operation in SABY_OPERATIONS:
        for result in RESULTS:
            SABY_OPS.labels(operation, result)


_prime_series()


class DatabaseCollector:
    """Читает состояние из БД при каждом опросе /metrics."""

    def __init__(self, app):
        self.app = app

    def collect(self):
        from hrpanel.extensions import db
        from hrpanel.services import DEPARTMENTS, EMPLOYEE_ROLES
        from models import ActionLog, Employee, LoginHistory, User
        from sqlalchemy import func, text

        up = GaugeMetricFamily("hrpanel_database_up", "1 — база данных отвечает")
        latency = GaugeMetricFamily("hrpanel_database_query_seconds", "Время простого запроса SELECT 1")
        try:
            with self.app.app_context():
                started = time.perf_counter()
                db.session.execute(text("SELECT 1"))
                latency.add_metric([], time.perf_counter() - started)

                # Все комбинации выдаём всегда (с нулями): пустая БД не должна «ронять» элементы Zabbix и графики
                by_role = {(status, role): 0 for status in ("active", "disabled") for role in EMPLOYEE_ROLES}
                for role, active, count in db.session.query(Employee.role, Employee.is_active, func.count()).group_by(Employee.role, Employee.is_active):
                    by_role[("active" if active else "disabled", role)] = count
                employees = GaugeMetricFamily("hrpanel_employees", "Сотрудники по статусу и роли", labels=["status", "role"])
                for (status, role), count in by_role.items():
                    employees.add_metric([status, role], count)

                by_dept = {(dept, status): 0 for dept in DEPARTMENTS for status in ("active", "disabled")}
                for dept, active, count in db.session.query(Employee.department, Employee.is_active, func.count()).group_by(Employee.department, Employee.is_active):
                    by_dept[(dept, "active" if active else "disabled")] = count
                by_department = GaugeMetricFamily("hrpanel_employees_by_department", "Сотрудники по отделам и статусу",
                                                  labels=["department", "status"])
                for (dept, status), count in by_dept.items():
                    by_department.add_metric([dept, status], count)

                since_day = datetime.utcnow() - timedelta(hours=24)
                created = GaugeMetricFamily("hrpanel_employees_created_last_24h", "Создано сотрудников за 24 часа")
                created.add_metric([], db.session.query(func.count(Employee.id)).filter(Employee.created_at >= since_day).scalar() or 0)

                users_by_role = {role: 0 for role in ("admin", "hr", "manager")}
                for role, count in db.session.query(User.role, func.count()).group_by(User.role):
                    users_by_role[role] = count
                panel_users = GaugeMetricFamily("hrpanel_panel_users", "Пользователи панели по ролям", labels=["role"])
                for role, count in users_by_role.items():
                    panel_users.add_metric([role], count)
                pending = GaugeMetricFamily("hrpanel_panel_users_pending_password_change",
                                            "Пользователи, которые ещё не сменили выданный пароль")
                pending.add_metric([], db.session.query(func.count(User.id)).filter(User.must_change_password.is_(True)).scalar() or 0)

                recent = GaugeMetricFamily("hrpanel_logins_recent", "Попытки входа за окно по результату",
                                           labels=["result", "window"])
                now = datetime.utcnow()
                counts = {(r, w): 0 for r in ("success", "failed") for w in ("15m", "24h")}
                for success, ts in db.session.query(LoginHistory.success, LoginHistory.timestamp).filter(LoginHistory.timestamp >= since_day):
                    result = "success" if success else "failed"
                    counts[(result, "24h")] += 1
                    if ts >= now - timedelta(minutes=15):
                        counts[(result, "15m")] += 1
                for (result, window), count in counts.items():
                    recent.add_metric([result, window], count)

                last_action = GaugeMetricFamily("hrpanel_last_action_timestamp_seconds", "Unix-время последнего действия в журнале")
                last = db.session.query(func.max(ActionLog.timestamp)).scalar()
                if last:
                    last_action.add_metric([], (last - datetime(1970, 1, 1)).total_seconds())

            up.add_metric([], 1)
            yield from (up, latency, employees, by_department, created, panel_users, pending, recent, last_action)
        except Exception:  # БД недоступна — отдаём только признак, не роняем весь /metrics
            log.exception("Сбор метрик из БД не удался")
            up.add_metric([], 0)
            yield up


_state = {"collector": None}


def register_metrics(app):
    """Подключает счётчики запросов и сборщик метрик БД; выставляет информационные метрики."""
    import ad_utils  # DRY_RUN читается из окружения при импорте

    if _state["collector"] is not None:   # повторный create_app (тесты): не дублируем серии
        REGISTRY.unregister(_state["collector"])
    _state["collector"] = DatabaseCollector(app)
    REGISTRY.register(_state["collector"])

    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    APP_INFO.clear()
    APP_INFO.labels(app.config.get("APP_VERSION", "dev"), uri.split(":")[0].split("+")[0] or "unknown").set(1)
    for flag, value in (("dry_run", ad_utils.DRY_RUN), ("saby_enabled", app.config.get("SABY_ENABLED")),
                        ("ad_sync_changes", app.config.get("AD_SYNC_CHANGES"))):
        FEATURE_FLAGS.labels(flag).set(1 if value else 0)

    @app.before_request
    def metrics_start():
        g.metrics_counted = request.endpoint not in SKIP_ENDPOINTS
        g.metrics_released = False   # g может пережить запрос (общий контекст приложения), поэтому сбрасываем явно
        if g.metrics_counted:
            g.metrics_started = time.perf_counter()
            HTTP_IN_PROGRESS.inc()

    @app.after_request
    def metrics_observe(response):
        if getattr(g, "metrics_counted", False):
            endpoint = request.endpoint or "unmatched"   # 404 на несуществующий путь — одна серия, а не по каждому пути
            method = request.method if request.method in ALLOWED_METHODS else "OTHER"
            HTTP_REQUESTS.labels(method, endpoint, str(response.status_code)).inc()
            HTTP_HANDLED.inc()
            if response.status_code >= 500:
                HTTP_SERVER_ERRORS.inc()
            HTTP_DURATION.labels(endpoint).observe(time.perf_counter() - g.metrics_started)
        return response

    @app.teardown_request
    def metrics_done(_exc):
        if getattr(g, "metrics_counted", False) and not getattr(g, "metrics_released", False):
            g.metrics_released = True
            HTTP_IN_PROGRESS.dec()
