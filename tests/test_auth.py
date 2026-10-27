from conftest import PASSWORD, login


def test_login_ok_and_me(client):
    assert login(client, "admin").json["ok"] is True
    me = client.get("/api/me").json
    assert me["ok"] and me["role"] == "admin"


def test_login_wrong_password_counts_attempts(client):
    r = login(client, "admin", "wrong")
    assert r.status_code == 401
    assert "Осталось попыток: 4" in r.json["message"]


def test_login_garbage_body_does_not_crash(client):
    assert client.post("/api/login", json={"login": None, "password": None}).status_code == 401
    assert client.post("/api/login", data="not json").status_code == 401


def test_lockout_after_five_failures(client):
    for _ in range(4):
        assert login(client, "admin", "wrong").status_code == 401
    r = login(client, "admin", "wrong")
    assert r.status_code == 429 and r.json["seconds"] > 0
    # даже верный пароль не пускает, пока идёт блокировка
    assert login(client, "admin").status_code == 429
    assert client.get("/api/check_lockout?login=admin").json["locked"] is True


def test_lockout_is_not_bypassed_by_dropping_cookies(app):
    for _ in range(5):
        login(app.test_client(), "admin", "wrong")  # каждый раз «новый браузер» без cookie
    assert login(app.test_client(), "admin").status_code == 429


def test_lockout_is_per_username(client):
    for _ in range(5):
        login(client, "admin", "wrong")
    assert login(client, "hr_a").status_code == 200


def test_success_resets_failures(client):
    for _ in range(3):
        login(client, "admin", "wrong")
    assert login(client, "admin").status_code == 200
    for _ in range(4):
        assert login(client, "admin", "wrong").status_code == 401


def test_api_requires_auth(client):
    for path in ("/api/stats", "/api/employees", "/api/logs", "/api/logs/all", "/api/employees/export", "/api/profile"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/create", json={}).status_code == 401


def test_pages_redirect_when_anonymous(client):
    for path in ("/create", "/employees", "/profile", "/logs", "/users"):
        assert client.get(path).status_code == 302, path


def test_users_page_admin_only(as_user):
    assert as_user("admin").get("/users").status_code == 200
    assert as_user("hr_a").get("/users").status_code == 302


def test_deleted_user_loses_session(app, as_user):
    from models import db, User
    c = as_user("hr_a")
    db.session.delete(User.query.filter_by(username="hr_a").first())
    db.session.commit()
    assert c.get("/api/me").status_code == 401


def test_socketio_rejects_anonymous_and_accepts_user(app, client):
    from app import socketio
    anon = socketio.test_client(app, flask_test_client=client)
    assert not anon.is_connected()
    login(client, "admin")
    authed = socketio.test_client(app, flask_test_client=client)
    assert authed.is_connected()


def test_errors_are_json_on_api(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json["ok"] is False
    assert client.get("/api/login").status_code == 405


def test_csrf_blocks_requests_without_token(as_user):
    c = as_user("admin")
    assert c.post("/api/logout", no_csrf=True).status_code == 403
    assert c.post("/api/profile", json={"first_name": "X"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert c.get("/api/me").json["ok"] is True          # GET токена не требует
    assert c.post("/api/profile", json={"first_name": "X"}).status_code == 200  # клиент подставил верный токен


def test_csrf_token_is_in_page_and_changes_per_login(app):
    c = app.test_client()
    html = c.get("/").get_data(as_text=True)
    assert 'name="csrf-token"' in html
    login(c, "admin")
    with c.session_transaction() as s:
        first = s["csrf"]
    c2 = app.test_client()
    login(c2, "admin")
    with c2.session_transaction() as s:
        assert s["csrf"] != first


def test_tls_verification_is_enabled_by_ca_file(monkeypatch, tmp_path):
    import ssl
    import ad_utils
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    monkeypatch.setattr(ad_utils, "AD_CA_CERTS_FILE", str(ca))
    monkeypatch.setattr(ad_utils, "AD_SERVER", "ldaps://dc01.corp.local")
    tls = ad_utils.build_tls()
    assert tls.validate == ssl.CERT_REQUIRED and tls.ca_certs_file == str(ca)
    assert tls.valid_names == ["dc01.corp.local"]
    monkeypatch.setattr(ad_utils, "AD_CA_CERTS_FILE", None)
    assert ad_utils.build_tls().validate == ssl.CERT_NONE
