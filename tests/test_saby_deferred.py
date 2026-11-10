"""AD-сценарии работают без установленного/доступного клиента СБИС."""
import builtins

from conftest import employee_payload


def test_saby_environment_flag_cannot_reenable_deferred_integration(monkeypatch):
    from flask import Flask
    from hrpanel.config import apply_config
    monkeypatch.setenv("SABY_ENABLED", "true")
    app = Flask(__name__)
    apply_config(app)
    assert app.config["SABY_ENABLED"] is False


def test_create_and_disable_employee_never_import_saby(app, as_user, monkeypatch):
    original_import = builtins.__import__
    calls = []

    def guarded_import(name, *args, **kwargs):
        if name in {"saby_utils", "saby_config", "pysaby"}:
            calls.append(name)
            raise AssertionError("Deferred integration must not be loaded")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    # Даже изменение флага в памяти не должно вернуть вынесенные вызовы.
    monkeypatch.setitem(app.config, "SABY_ENABLED", True)
    client = as_user("admin")
    created = client.post("/api/create", json=employee_payload())
    assert created.status_code == 200 and created.json["ok"]
    assert "Saby" not in created.json["message"]
    employee = client.get("/api/employees").json["employees"][0]
    disabled = client.post(f"/api/employee/{employee['id']}/disable", json={})
    assert disabled.status_code == 200 and disabled.json["ok"]
    assert "СБИС" not in disabled.json["message"]
    assert calls == []
