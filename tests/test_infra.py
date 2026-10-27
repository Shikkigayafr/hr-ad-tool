import json
import logging
import os
import sqlite3
import subprocess
import sys

import pytest

import ad_utils
import secret_utils
from conftest import DEPT_A, DEPT_B, PASSWORD, employee_payload
from hrpanel.config import database_uri
from hrpanel.logging_config import JsonFormatter
from hrpanel.validators import generate_password, password_error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_employee(admin, login_name="stager.a", department=DEPT_A, role="Sbis_Stager"):
    assert admin.post("/api/create", json=employee_payload(login_name, department, role)).status_code == 200
    emps = admin.get("/api/employees").json["employees"]
    return next(e for e in emps if e["department"] == department and e["role"] == role)["id"]


# --- сброс пароля сотрудника ---
def test_reset_password_generates_valid_one_time_password(as_user, caplog):
    caplog.set_level(logging.INFO, logger="hrpanel")
    admin = as_user("admin")
    emp_id = make_employee(admin)

    r = admin.post(f"/api/employee/{emp_id}/reset-password", json={})
    assert r.status_code == 200 and r.json["ok"]
    new_password = r.json["password"]
    assert password_error(new_password) is None
    assert r.headers["Cache-Control"] == "no-store"

    # пароль не попал ни в журнал действий, ни в логи
    logs = admin.get("/api/logs/all").json["logs"]
    assert any("сбросил пароль" in l["action"] for l in logs)
    assert all(new_password not in l["action"] for l in logs)
    formatter = JsonFormatter()
    assert all(new_password not in formatter.format(rec) for rec in caplog.records)
    assert any(getattr(rec, "fields", {}).get("event") == "password_reset" for rec in caplog.records)


def test_reset_password_accepts_custom_and_rejects_weak(as_user):
    admin = as_user("admin")
    emp_id = make_employee(admin)
    assert admin.post(f"/api/employee/{emp_id}/reset-password", json={"password": "weak"}).status_code == 400
    r = admin.post(f"/api/employee/{emp_id}/reset-password", json={"password": "Custom1!pass"})
    assert r.status_code == 200 and r.json["password"] == "Custom1!pass"


def test_reset_password_permissions(as_user):
    admin = as_user("admin")
    stager = make_employee(admin, "stager.a")
    main = make_employee(admin, "main.a", role="Sbis_Main")
    other_dept = make_employee(admin, "stager.b", department=DEPT_B)

    hr = as_user("hr_a")
    assert hr.post(f"/api/employee/{stager}/reset-password", json={}).status_code == 200
    assert hr.post(f"/api/employee/{main}/reset-password", json={}).status_code == 403   # HR — только стажёрам
    assert hr.post(f"/api/employee/{other_dept}/reset-password", json={}).status_code == 404
    assert as_user("mgr_a").post(f"/api/employee/{main}/reset-password", json={}).status_code == 200


def test_reset_password_blocked_when_ad_changes_disabled(app, as_user, monkeypatch):
    admin = as_user("admin")
    emp_id = make_employee(admin)
    monkeypatch.setattr(ad_utils, "DRY_RUN", False)
    monkeypatch.setitem(app.config, "AD_SYNC_CHANGES", False)
    assert admin.post(f"/api/employee/{emp_id}/reset-password", json={}).status_code == 503


def test_reset_password_ad_failure_is_reported(as_user, monkeypatch):
    admin = as_user("admin")
    emp_id = make_employee(admin)
    monkeypatch.setattr(ad_utils, "reset_password", lambda *a, **k: (False, "boom"))
    r = admin.post(f"/api/employee/{emp_id}/reset-password", json={})
    assert r.status_code == 500 and "boom" in r.json["message"] and "password" not in r.json
    assert not any("сбросил пароль" in l["action"] for l in admin.get("/api/logs/all").json["logs"])


def test_generated_passwords_always_pass_policy():
    seen = {generate_password() for _ in range(200)}
    assert all(password_error(p) is None and len(p) == 14 for p in seen)
    assert len(seen) == 200  # случайные, без повторов


# --- JSON-логи ---
def test_json_formatter_outputs_one_json_object_per_line():
    record = logging.LogRecord("hrpanel.test", logging.INFO, __file__, 1, "привет %s", ("мир",), None)
    record.fields = {"event": "x", "n": 1}
    data = json.loads(JsonFormatter().format(record))
    assert data["msg"] == "привет мир" and data["event"] == "x" and data["level"] == "INFO"
    assert data["ts"].endswith("+00:00")


def test_request_log_has_status_user_and_request_id(as_user, caplog):
    caplog.set_level(logging.INFO, logger="hrpanel")
    c = as_user("hr_a")
    r = c.get("/api/employees", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    rec = next(x for x in caplog.records if x.name == "hrpanel.request" and x.fields["path"] == "/api/employees")
    assert rec.fields["status"] == 200 and rec.fields["user"] == "hr_a" and rec.fields["request_id"] == "abc-123"
    # мусорный X-Request-ID заменяется своим
    bad = c.get("/api/me", headers={"X-Request-ID": "bad id <script>"})
    assert bad.headers["X-Request-ID"] != "bad id <script>"


def test_health_and_static_are_not_logged(client, caplog):
    caplog.set_level(logging.INFO, logger="hrpanel")
    client.get("/health")
    assert not [r for r in caplog.records if r.name == "hrpanel.request"]


def test_login_events_are_audited_without_passwords(client, caplog):
    caplog.set_level(logging.INFO, logger="hrpanel")
    client.post("/api/login", json={"login": "admin", "password": "WrongPass1!"})
    client.post("/api/login", json={"login": "admin", "password": PASSWORD})
    events = [r.fields["event"] for r in caplog.records if r.name == "hrpanel.audit"]
    assert events == ["login_failed", "login_success"]
    dump = " ".join(JsonFormatter().format(r) for r in caplog.records)
    assert "WrongPass1!" not in dump and PASSWORD not in dump


# --- секреты и настройки БД ---
def test_read_secret_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_utils, "SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("DEMO_SECRET", raising=False)
    monkeypatch.delenv("DEMO_SECRET_FILE", raising=False)
    assert secret_utils.read_secret("DEMO_SECRET", "default") == "default"

    monkeypatch.setenv("DEMO_SECRET", "from-env")
    assert secret_utils.read_secret("DEMO_SECRET") == "from-env"

    (tmp_path / "demo_secret").write_text("from-docker-secret\n", encoding="utf-8")   # /run/secrets/demo_secret
    assert secret_utils.read_secret("DEMO_SECRET") == "from-docker-secret"

    custom = tmp_path / "custom.txt"
    custom.write_text("from-file-var", encoding="utf-8")
    monkeypatch.setenv("DEMO_SECRET_FILE", str(custom))                              # NAME_FILE важнее всего
    assert secret_utils.read_secret("DEMO_SECRET") == "from-file-var"


def test_database_uri_variants(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host/db")
    assert database_uri() == "postgresql+psycopg2://u:p@host/db"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    assert database_uri() == "postgresql+psycopg2://u:p@host/db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    assert database_uri() == "sqlite:///x.db"

    monkeypatch.delenv("DATABASE_URL")
    assert database_uri() == "sqlite:///hr.db"

    monkeypatch.setattr(secret_utils, "SECRETS_DIR", str(tmp_path))
    (tmp_path / "postgres_password").write_text("p@ss/word:1\n", encoding="utf-8")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_USER", "hrpanel")
    uri = database_uri()
    assert uri.startswith("postgresql+psycopg2://hrpanel:") and uri.endswith("@db:5432/hrpanel")
    assert "p@ss/word:1" not in uri  # спецсимволы пароля экранированы


# --- миграции (в отдельном процессе, на файловой SQLite) ---
def run_cli(db_path, *args):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}", "LOG_TO_FILE": "false", "DRY_RUN": "true"}
    return subprocess.run([sys.executable, "-m", "flask", "--app", "app", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def table_names(db_path):
    with sqlite3.connect(db_path) as conn:
        return {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}


def alembic_version(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("select version_num from alembic_version").fetchone()[0]


def test_migrations_on_fresh_database_are_idempotent(tmp_path):
    db_path = tmp_path / "fresh.db"
    for _ in range(2):  # второй запуск ничего не ломает
        result = run_cli(db_path, "upgrade-db")
        assert result.returncode == 0, result.stderr
    assert {"user", "employee", "action_log", "login_history", "alembic_version"} <= table_names(db_path)
    assert alembic_version(db_path) == "0002"


def test_migrations_adopt_legacy_database_created_before_alembic(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:  # схема и данные, как у старого create_all()
        conn.executescript("""
            CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(80) NOT NULL UNIQUE,
                password_hash VARCHAR(128) NOT NULL, first_name VARCHAR(50), avatar VARCHAR(200),
                role VARCHAR(20) NOT NULL, department VARCHAR(100));
            CREATE TABLE employee (id INTEGER PRIMARY KEY, full_name VARCHAR(150) NOT NULL,
                login VARCHAR(80) NOT NULL UNIQUE, department VARCHAR(100) NOT NULL,
                role VARCHAR(50) NOT NULL, created_at DATETIME);
            CREATE TABLE action_log (id INTEGER PRIMARY KEY, user_name VARCHAR(100) NOT NULL,
                user_role VARCHAR(20) NOT NULL, department VARCHAR(100), action VARCHAR(200) NOT NULL, timestamp DATETIME);
            CREATE TABLE login_history (id INTEGER PRIMARY KEY, username VARCHAR(80) NOT NULL,
                ip_address VARCHAR(50), success BOOLEAN, timestamp DATETIME);
            INSERT INTO user (username, password_hash, role) VALUES ('old_admin', 'hash', 'admin');
            INSERT INTO employee (full_name, login, department, role) VALUES ('Старый Сотрудник', 'old.emp', 'Офис', 'Sbis_Main');
        """)
    result = run_cli(db_path, "upgrade-db")
    assert result.returncode == 0, result.stderr
    assert alembic_version(db_path) == "0002"
    with sqlite3.connect(db_path) as conn:   # данные на месте
        assert conn.execute("select username from user").fetchall() == [("old_admin",)]
        assert conn.execute("select full_name from employee").fetchall() == [("Старый Сотрудник",)]


def test_init_db_creates_admin_with_given_password(tmp_path):
    db_path = tmp_path / "init.db"
    env_pwd = "Init-Pass1!"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}", "LOG_TO_FILE": "false",
           "INITIAL_ADMIN_PASSWORD": env_pwd}
    result = subprocess.run([sys.executable, "-m", "flask", "--app", "app", "init-db"], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert f"admin / {env_pwd}" in result.stdout
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("select username, role from user").fetchall() == [("admin", "admin")]
