"""Отключение вместо удаления, импорт CSV, принудительная смена пароля."""
import io
import logging

import pytest

import ad_utils
from conftest import DEPT_A, DEPT_B, PASSWORD, employee_payload, login
from hrpanel.employee_service import MAX_IMPORT_ROWS
from models import Employee, User, db


def create(client, login_name="stager.a", department=DEPT_A, role="Sbis_Stager"):
    assert client.post("/api/create", json=employee_payload(login_name, department, role)).status_code == 200
    return next(e["id"] for e in client.get("/api/employees").json["employees"] if e["department"] == department
                and e["role"] == role)


# --- отключение вместо удаления ---
def test_disable_and_enable_cycle(as_user):
    admin = as_user("admin")
    emp_id = create(admin)

    r = admin.post(f"/api/employee/{emp_id}/disable", json={"reason": "Увольнение по собственному"})
    assert r.status_code == 200
    emp = next(e for e in admin.get("/api/employees").json["employees"] if e["id"] == emp_id)
    assert emp["is_active"] is False and emp["disabled_reason"] == "Увольнение по собственному" and emp["disabled_at"]

    assert admin.post(f"/api/employee/{emp_id}/disable", json={}).status_code == 400   # уже отключён
    assert admin.post(f"/api/employee/{emp_id}/promote").status_code == 400             # с отключённым ничего нельзя
    assert admin.post(f"/api/employee/{emp_id}/reset-password", json={}).status_code == 400

    assert admin.post(f"/api/employee/{emp_id}/enable").status_code == 200
    assert admin.post(f"/api/employee/{emp_id}/enable").status_code == 400
    emp = next(e for e in admin.get("/api/employees").json["employees"] if e["id"] == emp_id)
    assert emp["is_active"] is True and emp["disabled_reason"] is None


def test_disabled_employees_are_excluded_from_stats_but_kept_in_export(as_user):
    admin = as_user("admin")
    keep, gone = create(admin, "keep.me"), create(admin, "gone.me", role="Sbis_Main")
    admin.post(f"/api/employee/{gone}/disable", json={})
    assert admin.get("/api/stats").json["total"] == 1
    csv_text = admin.get("/api/employees/export").data.decode("utf-8")
    assert "Отключён" in csv_text and "Работает" in csv_text


def test_hard_delete_requires_admin_and_disabled(as_user):
    admin = as_user("admin")
    emp_id = create(admin)
    assert as_user("hr_a").delete(f"/api/employee/{emp_id}").status_code == 403
    assert as_user("mgr_a").delete(f"/api/employee/{emp_id}").status_code == 403
    assert admin.delete(f"/api/employee/{emp_id}").status_code == 409        # ещё работает
    admin.post(f"/api/employee/{emp_id}/disable", json={})
    assert admin.delete(f"/api/employee/{emp_id}").status_code == 200
    assert admin.get("/api/employees").json["employees"] == []


def test_disable_log_text_is_truncated_for_long_reasons(as_user):
    admin = as_user("admin")
    emp_id = create(admin)
    assert admin.post(f"/api/employee/{emp_id}/disable", json={"reason": "я" * 500}).status_code == 200
    logs = admin.get("/api/logs/all").json["logs"]
    assert all(len(l["action"]) <= 200 for l in logs)


def test_disable_calls_ad_with_group_when_sync_enabled(app, as_user, monkeypatch):
    calls = []
    monkeypatch.setitem(app.config, "AD_SYNC_CHANGES", True)
    monkeypatch.setattr(ad_utils, "disable_user", lambda login, reason, group_dn=None: calls.append((login, reason, group_dn)) or (True, "ok"))
    admin = as_user("admin")
    emp_id = create(admin, "ad.sync")
    assert admin.post(f"/api/employee/{emp_id}/disable", json={"reason": "тест"}).status_code == 200
    assert calls == [("ad.sync", "тест", ad_utils.get_group_dn("Sbis_Stager"))]

    monkeypatch.setattr(ad_utils, "disable_user", lambda *a, **k: (False, "AD недоступен"))
    other = create(admin, "ad.fail", department=DEPT_B)
    r = admin.post(f"/api/employee/{other}/disable", json={})
    assert r.status_code == 500 and Employee.query.get(other).is_active is True   # при ошибке AD в панели не меняем


# --- импорт CSV ---
def csv_file(text, name="import.csv", encoding="utf-8-sig"):
    return {"file": (io.BytesIO(text.encode(encoding)), name)}


def post_import(client, text, dry_run=False, **kwargs):
    url = "/api/employees/import" + ("?dry_run=1" if dry_run else "")
    return client.post(url, data=csv_file(text, **kwargs), content_type="multipart/form-data")


GOOD_CSV = """ФИО;Логин;Email;Отдел;Роль;Пароль
Петров Пётр Петрович;petrov.pp;petrov@evostor.ru;Офис;Стажер;
Сидорова Анна;sidorova.a;;Офис;Основной;Custom1!pass
"""


def test_import_dry_run_creates_nothing(as_user):
    admin = as_user("admin")
    r = post_import(admin, GOOD_CSV, dry_run=True)
    assert r.status_code == 200 and r.json["dry_run"] and r.json["created"] == 2 and r.json["failed"] == 0
    assert admin.get("/api/employees").json["employees"] == []


def test_import_creates_rows_and_returns_generated_passwords_once(as_user, caplog):
    caplog.set_level(logging.INFO, logger="hrpanel")
    admin = as_user("admin")
    r = post_import(admin, GOOD_CSV)
    assert r.status_code == 200 and r.json["created"] == 2
    assert r.headers["Cache-Control"] == "no-store"
    rows = {row["login"]: row for row in r.json["rows"]}
    assert len(rows["petrov.pp"]["password"]) == 14                 # сгенерирован
    assert "password" not in rows["sidorova.a"]                      # свой пароль обратно не отдаём
    assert {e["role"] for e in admin.get("/api/employees").json["employees"]} == {"Sbis_Stager", "Sbis_Main"}
    dump = " ".join(str(getattr(rec, "fields", "")) + rec.getMessage() for rec in caplog.records)
    assert rows["petrov.pp"]["password"] not in dump and "Custom1!pass" not in dump


def test_import_reports_bad_rows_but_continues(as_user):
    text = """ФИО,Логин,Отдел,Роль
Нормальный Человек,norm.user,Офис,Стажер
Плохой,b a d,Офис,Стажер
Другой Отдел,other.dep,Несуществующий,Стажер
Дубль Логина,norm.user,Офис,Стажер
Без Роли,no.role,Офис,
"""
    admin = as_user("admin")
    r = post_import(admin, text)
    assert r.status_code == 200 and r.json["created"] == 2 and r.json["failed"] == 3   # запятая как разделитель тоже ок
    by_login = {row["login"]: row for row in r.json["rows"]}
    assert by_login["no.role"]["ok"] and by_login["no.role"]["role"] == "Sbis_Stager"
    assert "повторяется" in [row for row in r.json["rows"] if row["line"] == 5][0]["message"]


def test_import_respects_department_permissions(as_user):
    text = f"ФИО;Логин;Отдел;Роль\nВ Моём Отделе;mine.dep;;Стажер\nЧужой Отдел;foreign.dep;{DEPT_B};Стажер\nСтарший Хотел;senior.try;{DEPT_A};Старший\n"
    hr = as_user("hr_a")
    r = post_import(hr, text)
    by_login = {row["login"]: row for row in r.json["rows"]}
    assert by_login["mine.dep"]["ok"] and by_login["mine.dep"]["department"] == DEPT_A   # пустой отдел = свой
    assert not by_login["foreign.dep"]["ok"] and "Нет прав" in by_login["foreign.dep"]["message"]
    assert not by_login["senior.try"]["ok"]


@pytest.mark.parametrize("text, expected", [
    ("", "пустой"),
    ("Имя;Фамилия\nа;б\n", "Логин"),
    ("ФИО;Логин\n", "нет данных"),
])
def test_import_rejects_bad_files(as_user, text, expected):
    r = post_import(as_user("admin"), text)
    assert r.status_code == 400 and expected.lower() in r.json["message"].lower()


def test_import_limits_and_encodings(as_user):
    admin = as_user("admin")
    too_many = "ФИО;Логин\n" + "".join(f"Человек Номер{i};user{i:04d}\n" for i in range(MAX_IMPORT_ROWS + 1))
    assert post_import(admin, too_many).status_code == 400
    cp1251 = post_import(admin, "ФИО;Логин;Отдел\nИванов Иван;ivanov.i;Офис\n", encoding="cp1251")   # Excel «CSV (разделители — точка с запятой)»
    assert cp1251.status_code == 200 and cp1251.json["created"] == 1
    assert admin.post("/api/employees/import", data={}, content_type="multipart/form-data").status_code == 400


def test_import_template_download(as_user):
    r = as_user("hr_a").get("/api/employees/import/template")
    text = r.data.decode("utf-8-sig")
    assert text.startswith("ФИО;Логин;Email;Отдел;Роль;Пароль") and r.data.startswith(b"\xef\xbb\xbf")
    assert as_user("hr_a").get("/import").status_code == 200


# --- принудительная смена пароля ---
def test_admin_created_panel_user_must_change_password(as_user, app):
    admin = as_user("admin")
    temp = "Temp0rary!pw"
    assert admin.post("/api/users", json={"username": "new.hr", "password": temp, "role": "hr",
                                           "department": DEPT_A}).json["user"]["must_change_password"] is True

    c = app.test_client()
    r = login(c, "new.hr", temp)
    assert r.status_code == 200 and r.json["must_change_password"] is True

    # всё заблокировано, кроме профиля и смены пароля
    blocked = c.get("/api/employees")
    assert blocked.status_code == 403 and blocked.json["code"] == "password_change_required"
    assert c.get("/api/stats").status_code == 403
    page = c.get("/employees")
    assert page.status_code == 302 and "/profile" in page.headers["Location"]
    assert c.get("/").status_code == 302
    assert c.get("/profile").status_code == 200
    assert c.get("/api/profile").json["must_change_password"] is True
    assert c.get("/api/me").json["must_change_password"] is True

    # смена пароля снимает ограничение
    assert c.post("/api/profile/password", json={"old_password": temp, "new_password": "Brand-New1!"}).status_code == 200
    assert c.get("/api/employees").status_code == 200
    assert c.get("/api/me").json["must_change_password"] is False
    assert login(app.test_client(), "new.hr", "Brand-New1!").json["must_change_password"] is False


def test_logout_works_while_password_change_is_pending(as_user, app):
    admin = as_user("admin")
    admin.post("/api/users", json={"username": "temp.user", "password": "Temp0rary!pw", "role": "admin"})
    c = app.test_client()
    login(c, "temp.user", "Temp0rary!pw")
    assert c.post("/api/logout").status_code == 200


def test_admin_password_reset_marks_temporary_but_not_for_self(as_user, app):
    admin = as_user("admin")
    hr_id = User.query.filter_by(username="hr_a").first().id
    admin_id = User.query.filter_by(username="admin").first().id
    admin.post(f"/api/users/{hr_id}/password", json={"new_password": "Reset0k!!1"})
    assert User.query.get(hr_id).must_change_password is True
    admin.post(f"/api/users/{admin_id}/password", json={"new_password": "Mine0wn!!1"})
    assert User.query.get(admin_id).must_change_password is False
    assert PASSWORD  # (пароли фикстур не затронуты для остальных пользователей)
