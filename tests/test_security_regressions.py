"""Регрессии: отзыв доступа, границы доверия proxy и проверка TLS."""
import pytest

from conftest import PASSWORD, login
from hrpanel.extensions import db, socketio
from models import User


def test_password_change_revokes_other_browser_and_socket(app, as_user):
    current, other = as_user("hr_a"), as_user("hr_a")
    ws = socketio.test_client(app, flask_test_client=other)
    assert ws.is_connected()
    assert current.post("/api/profile/password", json={
        "old_password": PASSWORD, "new_password": "Changed1!pass",
    }).status_code == 200
    assert current.get("/api/me").status_code == 200
    assert other.get("/api/me").status_code == 401
    assert not ws.is_connected()
    assert not socketio.test_client(app, flask_test_client=other).is_connected()


def test_admin_reset_revokes_http_and_socket(app, as_user):
    admin, hr = as_user("admin"), as_user("hr_a")
    ws = socketio.test_client(app, flask_test_client=hr)
    uid = User.query.filter_by(username="hr_a").one().id
    assert admin.post(f"/api/users/{uid}/password", json={"new_password": "Reset1!pass"}).status_code == 200
    assert hr.get("/api/me").status_code == 401
    assert not ws.is_connected()
    assert login(hr, "hr_a", "Reset1!pass").status_code == 200
    assert not socketio.test_client(app, flask_test_client=hr).is_connected()


def test_logout_closes_only_current_browser_socket(app, as_user):
    first, second = as_user("hr_a"), as_user("hr_a")
    ws1 = socketio.test_client(app, flask_test_client=first)
    ws2 = socketio.test_client(app, flask_test_client=second)
    assert first.post("/api/logout").status_code == 200
    assert not ws1.is_connected()
    assert ws2.is_connected()
    ws2.disconnect()


def test_old_cookie_without_password_binding_is_rejected(app, as_user):
    c = as_user("hr_a")
    with c.session_transaction() as sess:
        sess.pop("auth_tag")
    assert c.get("/api/me").status_code == 401
    assert not socketio.test_client(app, flask_test_client=c).is_connected()


@pytest.mark.parametrize("change", ["role", "department", "delete", "password"])
def test_socket_cannot_receive_events_after_access_changes(app, as_user, change):
    from hrpanel.services import notify_action
    from flask import g

    c = as_user("hr_a")
    ws = socketio.test_client(app, flask_test_client=c)
    assert ws.is_connected()
    user = User.query.filter_by(username="hr_a").one()
    if change == "role":
        user.role = "manager"
    elif change == "department":
        user.department = "Колл Центр"
    elif change == "delete":
        db.session.delete(user)
    else:
        user.set_password("Changed1!pass")
    db.session.commit()
    with app.test_request_context():
        # Событие HR того же отдела попало бы в старую комнату без проверки.
        g.user = User.query.filter_by(username="admin").one()
        notify_action("закрытое событие")
    assert not ws.is_connected()


def test_cross_origin_login_is_rejected(client):
    r = client.post("/api/login", json={"login": "admin", "password": PASSWORD},
                    headers={"Origin": "https://attacker.example"})
    assert r.status_code == 403
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("body", [[], [1], "text", 42, None])
def test_non_object_json_does_not_crash_api(client, body):
    import json
    assert client.post("/api/login", data=json.dumps(body), content_type="application/json").status_code == 400


def test_proxy_ignores_spoofed_first_forwarded_ip(app, monkeypatch):
    from hrpanel.security import client_ip
    monkeypatch.setitem(app.config, "TRUST_PROXY", True)
    with app.test_request_context(headers={"X-Forwarded-For": "spoofed, 192.0.2.10"}):
        assert client_ip() == "192.0.2.10"
    monkeypatch.setitem(app.config, "TRUST_PROXY", False)
    with app.test_request_context(headers={"X-Forwarded-For": "spoofed"}, environ_base={"REMOTE_ADDR": "192.0.2.20"}):
        assert client_ip() == "192.0.2.20"


def test_sensitive_responses_are_not_cached(client):
    for path in ("/", "/api/me"):
        response = client.get(path)
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Frame-Options"] == "DENY"


def test_explicit_secret_file_fails_closed(tmp_path, monkeypatch):
    from secret_utils import read_secret
    monkeypatch.setenv("DEMO_SECRET", "fallback-must-not-be-used")
    path = tmp_path / "missing"
    monkeypatch.setenv("DEMO_SECRET_FILE", str(path))
    with pytest.raises(FileNotFoundError):
        read_secret("DEMO_SECRET")
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_secret("DEMO_SECRET")


def test_ad_without_service_credentials_never_connects(monkeypatch):
    import ad_utils
    monkeypatch.setattr(ad_utils, "AD_PASSWORD", None)
    monkeypatch.setattr(ad_utils, "Connection", lambda *a, **k: pytest.fail("Не должно быть подключения"))
    with pytest.raises(ValueError):
        ad_utils.get_connection()


@pytest.mark.parametrize("key", [None, "change_me_to_random_64_hex_chars"])
def test_production_refuses_missing_or_template_session_key(monkeypatch, key):
    from flask import Flask
    from hrpanel import config
    monkeypatch.setenv("FLASK_ENV", "production")
    original = config.read_secret
    monkeypatch.setattr(config, "read_secret", lambda name, *args: key if name == "SECRET_KEY" else original(name, *args))
    with pytest.raises(ValueError):
        config.apply_config(Flask(__name__))


def test_same_origin_login_works_behind_trusted_https_proxy(monkeypatch):
    from hrpanel import create_app
    # Отдельное приложение использует ту же тестовую БД в памяти, внешних вызовов нет.
    proxy_app = create_app({"TESTING": True, "TRUST_PROXY": True})
    with proxy_app.app_context():
        db.create_all()
        user = User(username="proxy-user", role="admin")
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        c = proxy_app.test_client()
        r = c.post("/api/login", json={"login": "proxy-user", "password": PASSWORD}, headers={
            "Host": "panel.example", "Origin": "https://panel.example",
            "X-Forwarded-Proto": "https", "X-Forwarded-For": "fake, 192.0.2.10",
        })
        assert r.status_code == 200
        db.session.remove()
        db.drop_all()
