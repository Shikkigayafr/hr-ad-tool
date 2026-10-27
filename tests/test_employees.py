from conftest import DEPT_A, DEPT_B, employee_payload


def create(client, **kwargs):
    return client.post("/api/create", json=employee_payload(**kwargs))


def test_admin_creates_employee_dry_run(as_user):
    admin = as_user("admin")
    r = create(admin)
    assert r.status_code == 200 and r.json["ok"]
    emps = admin.get("/api/employees").json["employees"]
    assert [e["full_name"] for e in emps] == ["Иванов Иван Иванович"]


def test_duplicate_login_rejected(as_user):
    admin = as_user("admin")
    assert create(admin).status_code == 200
    assert create(admin, login_name="IVANOV.II").status_code == 409


def test_validation(as_user):
    admin = as_user("admin")
    assert create(admin, login_name="a b").status_code == 400                    # плохой логин
    assert create(admin, role="Domain Admins").status_code == 400                 # чужая роль (инъекция в DN группы)
    assert create(admin, department="Несуществующий").status_code == 400
    assert create(admin, password="weak", confirm="weak").status_code == 400
    assert create(admin, confirm="Other0ne!x").status_code == 400
    assert create(admin, email="not-an-email").status_code == 400
    assert create(admin, full_name="Ив,CN=x").status_code == 400


def test_hr_limited_to_own_department_and_roles(as_user):
    hr = as_user("hr_a")
    assert create(hr, department=DEPT_A).status_code == 200
    assert create(hr, login_name="other.dep", department=DEPT_B).status_code == 403
    assert create(hr, login_name="senior.try", role="Sbis_Senior").status_code == 403


def test_scoping_in_list_export_and_stats(as_user):
    admin = as_user("admin")
    create(admin, login_name="emp.a", department=DEPT_A)
    create(admin, login_name="emp.b", department=DEPT_B)

    assert len(admin.get("/api/employees").json["employees"]) == 2
    hr_a = as_user("hr_a")
    emps = hr_a.get("/api/employees").json["employees"]
    assert len(emps) == 1 and emps[0]["department"] == DEPT_A
    assert hr_a.get("/api/stats").json["total"] == 1

    csv_text = hr_a.get("/api/employees/export").data.decode("utf-8")
    assert "emp.a" in csv_text and "emp.b" not in csv_text


def test_hr_cannot_touch_other_department(as_user):
    admin = as_user("admin")
    create(admin, login_name="emp.b", department=DEPT_B)
    emp_id = admin.get("/api/employees").json["employees"][0]["id"]
    assert as_user("hr_a").delete(f"/api/employee/{emp_id}").status_code == 404
    assert as_user("mgr_a").post(f"/api/employee/{emp_id}/promote").status_code == 404


def test_hr_deletes_only_stagers_and_cannot_promote(as_user):
    admin = as_user("admin")
    create(admin, login_name="stager.a")
    create(admin, login_name="main.a", role="Sbis_Main")
    emps = {e["role"]: e["id"] for e in admin.get("/api/employees").json["employees"]}

    hr = as_user("hr_a")
    assert hr.post(f"/api/employee/{emps['Sbis_Stager']}/promote").status_code == 403
    assert hr.delete(f"/api/employee/{emps['Sbis_Main']}").status_code == 403
    assert hr.delete(f"/api/employee/{emps['Sbis_Stager']}").status_code == 200


def test_manager_promotes_in_own_department(as_user):
    admin = as_user("admin")
    create(admin, login_name="stager.a")
    emp = admin.get("/api/employees").json["employees"][0]
    mgr = as_user("mgr_a")
    assert mgr.post(f"/api/employee/{emp['id']}/promote").status_code == 200
    assert mgr.post(f"/api/employee/{emp['id']}/promote").status_code == 400  # уже не стажёр
    assert mgr.get("/api/employees").json["employees"][0]["role"] == "Sbis_Main"


def test_csv_formula_injection_is_neutralised(as_user):
    admin = as_user("admin")
    # '=' не проходит валидацию ФИО, поэтому кладём запись напрямую
    from models import db, Employee
    db.session.add(Employee(full_name="=HYPERLINK(1)", login="evil.x", department=DEPT_A, role="Sbis_Stager"))
    db.session.commit()
    csv_text = admin.get("/api/employees/export").data.decode("utf-8")
    assert "'=HYPERLINK" in csv_text


def test_logs_visibility(as_user):
    create(as_user("admin"), login_name="by.admin", department=DEPT_B)
    create(as_user("hr_a"), login_name="by.hr.a", department=DEPT_A)
    create(as_user("hr_b"), login_name="by.hr.b", department=DEPT_B)

    assert as_user("admin").get("/api/logs/all").json["total"] == 3
    assert as_user("hr_a").get("/api/logs/all").json["total"] == 1      # только свой отдел и роль hr
    assert as_user("mgr_a").get("/api/logs/all").json["total"] == 1     # весь свой отдел
    assert as_user("admin").get("/api/logs/all?q=by.hr").json["total"] == 0  # ищем по тексту действия, а не по логину
    assert as_user("admin").get("/api/logs/all?q=Иванов").json["total"] == 3


def test_chart_data_counts_today(as_user):
    admin = as_user("admin")
    create(admin)
    data = admin.get("/api/chart_data").json
    assert data["data"][-1] == 1 and len(data["labels"]) == 7
