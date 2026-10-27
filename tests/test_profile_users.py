import io

from conftest import PASSWORD, login


def test_change_password_rules(as_user):
    c = as_user("hr_a")
    url = "/api/profile/password"
    assert c.post(url, json={"old_password": PASSWORD}).status_code == 400            # нет нового пароля
    assert c.post(url, json={"old_password": "bad", "new_password": "Newpass1!"}).status_code == 400
    assert c.post(url, json={"old_password": PASSWORD, "new_password": "weak"}).status_code == 400
    assert c.post(url, json={"old_password": PASSWORD, "new_password": PASSWORD}).status_code == 400
    assert c.post(url, json={"old_password": PASSWORD, "new_password": "Newpass1!"}).status_code == 200
    assert login(c, "hr_a", "Newpass1!").status_code == 200


def test_update_name(as_user):
    c = as_user("hr_a")
    assert c.post("/api/profile", json={"first_name": "  "}).status_code == 400
    assert c.post("/api/profile", json={"first_name": "x" * 51}).status_code == 400
    assert c.post("/api/profile", json={"first_name": "Анна"}).status_code == 200
    assert c.get("/api/profile").json["first_name"] == "Анна"


def test_avatar_upload(app, as_user, monkeypatch, tmp_path):
    monkeypatch.setattr(app, "root_path", str(tmp_path))  # не пишем в настоящую static/avatars
    c = as_user("hr_a")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    ok = c.post("/api/profile/avatar", data={"avatar": (io.BytesIO(png), "me.png")}, content_type="multipart/form-data")
    assert ok.status_code == 200 and ok.json["filename"].endswith(".png")
    # файл без расширения и не-картинка раньше валили сервер (500)
    noext = c.post("/api/profile/avatar", data={"avatar": (io.BytesIO(b"hello"), "noext")}, content_type="multipart/form-data")
    assert noext.status_code == 400
    fake = c.post("/api/profile/avatar", data={"avatar": (io.BytesIO(b"<?php ?>"), "shell.png")}, content_type="multipart/form-data")
    assert fake.status_code == 400
    assert c.post("/api/profile/avatar", data={}, content_type="multipart/form-data").status_code == 400


def test_panel_users_admin_only(as_user):
    hr = as_user("hr_a")
    assert hr.get("/api/users").status_code == 403
    assert hr.post("/api/users", json={}).status_code == 403


def test_admin_manages_panel_users(as_user):
    admin = as_user("admin")
    new = {"username": "hr.new", "password": PASSWORD, "role": "hr", "department": "Офис", "first_name": "Новая"}
    r = admin.post("/api/users", json=new)
    assert r.status_code == 200
    user_id = r.json["user"]["id"]

    assert admin.post("/api/users", json=new).status_code == 409                                  # дубль
    assert admin.post("/api/users", json={**new, "username": "x2", "role": "boss"}).status_code == 400
    assert admin.post("/api/users", json={**new, "username": "x3", "department": None}).status_code == 400
    assert admin.post("/api/users", json={**new, "username": "x4", "password": "weak"}).status_code == 400

    assert admin.post(f"/api/users/{user_id}/password", json={"new_password": "weak"}).status_code == 400
    assert admin.post(f"/api/users/{user_id}/password", json={"new_password": "Reset0k!!"}).status_code == 200
    assert login(admin.application.test_client(), "hr.new", "Reset0k!!").status_code == 200

    assert admin.delete(f"/api/users/{user_id}").status_code == 200
    users = admin.get("/api/users").json["users"]
    admin_id = next(u["id"] for u in users if u["username"] == "admin")
    assert admin.delete(f"/api/users/{admin_id}").status_code == 400                              # себя нельзя
