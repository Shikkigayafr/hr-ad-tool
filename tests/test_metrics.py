"""Метрики Prometheus: защита токеном, содержимое и согласованность с дашбордом, правилами и шаблоном Zabbix."""
import glob
import json
import os
import re

import pytest
from prometheus_client.parser import text_string_to_metric_families

import ad_utils
from conftest import DEPT_A, PASSWORD, employee_payload, login
from hrpanel.extensions import db, socketio
from hrpanel.metrics import REGISTRY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "test-metrics-token"


@pytest.fixture
def scrape(app, monkeypatch):
    monkeypatch.setitem(app.config, "METRICS_TOKEN", TOKEN)
    client = app.test_client()

    def do():
        response = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200, response.get_data(as_text=True)
        samples = {}
        for family in text_string_to_metric_families(response.get_data(as_text=True)):
            for s in family.samples:
                samples[(s.name, tuple(sorted(s.labels.items())))] = s.value
        return samples
    return do


def value(samples, name, **labels):
    return samples.get((name, tuple(sorted(labels.items()))))


# --- доступ ---
def test_metrics_disabled_without_token(client):
    assert client.get("/metrics").status_code == 404


def test_metrics_requires_valid_bearer_token(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "METRICS_TOKEN", TOKEN)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": TOKEN}).status_code == 401           # без слова Bearer
    assert client.get("/metrics?token=" + TOKEN).status_code == 401                              # токен в URL не принимается
    r = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.content_type.startswith("text/plain")
    assert client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).get_data(as_text=True).startswith("# HELP")


def test_metrics_do_not_leak_secrets_or_personal_data(as_user, scrape):
    admin = as_user("admin")
    admin.post("/api/create", json=employee_payload("secret.login"))
    text = " ".join(f"{k}={v}" for k, v in scrape().items())
    assert PASSWORD not in text and TOKEN not in text
    assert "secret.login" not in text and "Иванов" not in text                                   # логинов и ФИО нет


# --- содержимое ---
def test_business_gauges_follow_database(as_user, scrape):
    admin = as_user("admin")
    admin.post("/api/create", json=employee_payload("stager.a"))
    admin.post("/api/create", json=employee_payload("main.a", role="Sbis_Main"))
    emp_id = admin.get("/api/employees").json["employees"][0]["id"]
    admin.post(f"/api/employee/{emp_id}/disable", json={})

    s = scrape()
    assert value(s, "hrpanel_database_up") == 1
    assert value(s, "hrpanel_database_query_seconds") >= 0
    active = sum(v for (n, l), v in s.items() if n == "hrpanel_employees" and dict(l)["status"] == "active")
    disabled = sum(v for (n, l), v in s.items() if n == "hrpanel_employees" and dict(l)["status"] == "disabled")
    assert (active, disabled) == (1, 1)
    assert value(s, "hrpanel_employees_by_department", department=DEPT_A, status="active") == 1
    assert value(s, "hrpanel_employees_created_last_24h") == 2
    assert value(s, "hrpanel_panel_users", role="hr") == 2
    assert value(s, "hrpanel_panel_users_pending_password_change") == 0
    assert value(s, "hrpanel_last_action_timestamp_seconds") > 1_700_000_000


def test_pending_password_change_and_login_windows(as_user, app, scrape):
    as_user("admin").post("/api/users", json={"username": "temp.hr", "password": "Temp0rary!pw", "role": "hr", "department": DEPT_A})
    c = app.test_client()
    login(c, "admin", "wrong-pass")
    login(c, "admin", "wrong-pass")
    s = scrape()
    assert value(s, "hrpanel_panel_users_pending_password_change") == 1
    assert value(s, "hrpanel_logins_recent", result="failed", window="15m") == 2
    assert value(s, "hrpanel_logins_recent", result="success", window="24h") == 1


def test_http_and_audit_counters_grow(as_user, app, scrape):
    before = scrape()
    c = as_user("admin")
    c.get("/api/employees")
    c.get("/api/employees")
    app.test_client().get("/api/employees")                                                      # 401
    after = scrape()

    def delta(name, **labels):
        return (value(after, name, **labels) or 0) - (value(before, name, **labels) or 0)

    assert delta("hrpanel_http_requests_total", method="GET", endpoint="employees.get_employees", status="200") == 2
    assert delta("hrpanel_http_requests_total", method="GET", endpoint="employees.get_employees", status="401") == 1
    assert delta("hrpanel_audit_events_total", event="login_success") == 1
    assert delta("hrpanel_http_request_duration_seconds_count", endpoint="employees.get_employees") == 3
    assert delta("hrpanel_http_requests_handled_total") >= 4                                      # безметочный счётчик для Zabbix
    assert value(after, "hrpanel_http_server_errors_total") is not None                           # существует даже при 0 ошибок
    assert value(after, "hrpanel_http_requests_in_progress") == 0                                 # счётчик «в работе» не утекает


def test_unmatched_paths_do_not_explode_cardinality(client, scrape):
    for i in range(5):
        client.get(f"/no-such-page-{i}")
    series = [dict(l)["endpoint"] for (n, l) in scrape() if n == "hrpanel_http_requests_total" and dict(l).get("status") == "404"]
    assert series.count("unmatched") == 1 and not any("no-such" in e for e in series)


def test_health_and_metrics_requests_are_not_counted(client, scrape):
    before = scrape()
    client.get("/health")
    client.get("/health")
    after = scrape()
    keys = {k for k in after if k[0] == "hrpanel_http_requests_total" and dict(k[1])["endpoint"] in ("system.health_check", "system.metrics")}
    assert not keys and before.get(("hrpanel_http_requests_in_progress", ())) == after.get(("hrpanel_http_requests_in_progress", ()))


def test_ad_operations_ok_fail_error_and_last_success(as_user, scrape, monkeypatch):
    admin = as_user("admin")
    before = scrape()
    admin.post("/api/create", json=employee_payload("ok.user"))                                   # DRY_RUN → ok

    monkeypatch.setattr(ad_utils, "create_user", lambda *a, **k: (False, "AD отказал"))
    assert admin.post("/api/create", json=employee_payload("fail.user")).status_code == 500

    def boom(*a, **k):
        raise ConnectionError("нет связи")
    monkeypatch.setattr(ad_utils, "create_user", boom)
    assert admin.post("/api/create", json=employee_payload("error.user")).status_code == 500

    after = scrape()
    for result in ("ok", "fail", "error"):
        assert value(after, "hrpanel_ad_operations_total", operation="create_user", result=result) - \
               (value(before, "hrpanel_ad_operations_total", operation="create_user", result=result) or 0) == 1, result
    assert value(after, "hrpanel_ad_last_success_timestamp_seconds", operation="create_user") > 1_700_000_000
    assert value(after, "hrpanel_ad_operation_duration_seconds_count", operation="create_user") >= 3


def test_other_ad_operations_are_instrumented(app, as_user, scrape, monkeypatch):
    monkeypatch.setitem(app.config, "AD_SYNC_CHANGES", True)
    admin = as_user("admin")
    admin.post("/api/create", json=employee_payload("ops.user"))
    emp_id = admin.get("/api/employees").json["employees"][0]["id"]
    before = scrape()
    admin.post(f"/api/employee/{emp_id}/reset-password", json={})
    admin.post(f"/api/employee/{emp_id}/promote")
    admin.post(f"/api/employee/{emp_id}/disable", json={})
    admin.post(f"/api/employee/{emp_id}/enable")
    admin.post(f"/api/employee/{emp_id}/disable", json={})
    admin.delete(f"/api/employee/{emp_id}")
    after = scrape()
    for operation in ("reset_password", "change_group", "disable_user", "enable_user", "delete_user"):
        assert (value(after, "hrpanel_ad_operations_total", operation=operation, result="ok") or 0) > \
               (value(before, "hrpanel_ad_operations_total", operation=operation, result="ok") or 0), operation


def test_database_down_is_reported_not_fatal(as_user, scrape, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("БД упала")
    monkeypatch.setattr(db.session, "execute", broken)
    s = scrape()                                                                                  # /metrics всё равно отвечает 200
    assert value(s, "hrpanel_database_up") == 0
    assert value(s, "hrpanel_feature_flag", flag="dry_run") == 1                                  # остальные метрики на месте


def test_feature_flags_and_info_are_exposed(scrape):
    s = scrape()
    assert value(s, "hrpanel_feature_flag", flag="dry_run") == 1
    assert value(s, "hrpanel_feature_flag", flag="saby_enabled") == 0
    assert value(s, "hrpanel_feature_flag", flag="ad_sync_changes") == 0
    assert any(n == "hrpanel_info" for (n, _l) in s)


def test_websocket_gauge_tracks_connections(app, as_user, scrape):
    c = as_user("admin")
    base = value(scrape(), "hrpanel_websocket_clients")      # другие тесты могли оставить свои соединения
    ws = socketio.test_client(app, flask_test_client=c)
    assert value(scrape(), "hrpanel_websocket_clients") == base + 1
    ws.disconnect()
    assert value(scrape(), "hrpanel_websocket_clients") == base


# --- согласованность мониторинга с кодом ---
def exposed_metric_names(scrape):
    names = {n for (n, _l) in scrape()}
    # у гистограмм в запросах встречаются суффиксы _bucket/_sum/_count, у счётчиков — _total
    return names | {re.sub(r"_(bucket|sum|count)$", "", n) for n in names}


def referenced_metrics(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(r"\b(?:hrpanel|process)_[a-z0-9_]+", text))


@pytest.mark.parametrize("pattern", [
    "monitoring/grafana/dashboards/*.json",
    "monitoring/prometheus/alerts.yml",
    "monitoring/zabbix/*.yaml",
])
def test_monitoring_files_only_reference_existing_metrics(scrape, pattern):
    """Если переименовать метрику в коде и забыть дашборд/шаблон — тест упадёт, а не график опустеет молча."""
    files = glob.glob(os.path.join(ROOT, pattern))
    assert files, pattern
    exposed = exposed_metric_names(scrape)
    for path in files:
        # метрики AD/Saby создаются заранее (нулевые серии), поэтому исключений для них нет
        missing = {m for m in referenced_metrics(path) if m not in exposed}
        if not os.path.exists("/proc/self/stat"):
            missing = {m for m in missing if not m.startswith("process_")}   # метрики процесса собираются только на Linux
        assert not missing, f"{os.path.relpath(path, ROOT)}: нет метрик {sorted(missing)}"


def test_grafana_dashboard_is_valid_and_uses_provisioned_datasource():
    with open(os.path.join(ROOT, "monitoring/grafana/dashboards/hrpanel.json"), encoding="utf-8") as f:
        dash = json.load(f)
    panels = [p for p in dash["panels"] if p["type"] != "row"]
    assert len(panels) >= 15 and dash["uid"] == "hrpanel-overview"
    assert len({p["id"] for p in dash["panels"]}) == len(dash["panels"])                          # id уникальны
    assert all(p["datasource"]["uid"] == "prometheus" for p in panels)
    assert all(t["expr"] for p in panels for t in p["targets"])


def test_zabbix_template_structure():
    with open(os.path.join(ROOT, "monitoring/zabbix/template_hrpanel_by_http.yaml"), encoding="utf-8") as f:
        text = f.read()
    uuids = re.findall(r"uuid: ([0-9a-f]{32})", text)
    assert len(uuids) == len(set(uuids)) >= 30                                                    # UUID уникальны
    assert all(u[12] == "4" for u in uuids)                                                       # версия UUID v4 требуется Zabbix
    keys = re.findall(r"^          key: (\S+)", text, flags=re.M)
    assert keys[0] == "hrpanel.metrics.raw" and len(keys) == len(set(keys))
    for trigger_key in re.findall(r"/HR AD Panel by HTTP/(hrpanel\.[a-z0-9_.]+)", text):
        assert trigger_key in keys, f"триггер ссылается на несуществующий элемент {trigger_key}"
