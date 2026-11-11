from cryptography.fernet import Fernet

from conftest import PASSWORD, employee_payload
from models import Employee, db


def test_admin_sees_only_confirmed_issued_password(app, as_user, monkeypatch):
    monkeypatch.setitem(app.extensions, 'employee_password_cipher', Fernet(Fernet.generate_key()))
    admin = as_user('admin')
    hr = as_user('hr_a')
    payload = employee_payload()
    assert admin.post('/api/create', json=payload).status_code == 200
    employee = Employee.query.one()
    assert employee.issued_password and PASSWORD not in employee.issued_password
    url = f'/api/employee/{employee.id}/reveal-password'
    page = admin.get('/employee-data')
    assert page.status_code == 200
    assert employee.login in page.text and PASSWORD not in page.text and employee.issued_password not in page.text
    assert hr.get('/employee-data').status_code == 302
    assert hr.post(url, json={'admin_password': PASSWORD}).status_code == 403
    assert admin.post(url, json={'admin_password': 'wrong'}).status_code == 403
    revealed = admin.post(url, json={'admin_password': PASSWORD})
    assert revealed.json == {'ok': True, 'password': PASSWORD}
    assert revealed.headers['Cache-Control'] == 'no-store'

    reset = admin.post(f'/api/employee/{employee.id}/reset-password', json={})
    assert reset.status_code == 200
    assert admin.post(url, json={'admin_password': PASSWORD}).json['password'] == reset.json['password']


def test_existing_employee_without_saved_password_remains_listed(as_user):
    admin = as_user('admin')
    employee = Employee(full_name='Ранее созданный сотрудник', login='legacy', department='Офис', role='Sbis_Main')
    db.session.add(employee)
    db.session.commit()
    page = admin.get('/employee-data')
    assert 'legacy' in page.text and 'Не сохранён' in page.text
    assert admin.post(f'/api/employee/{employee.id}/reveal-password', json={'admin_password': PASSWORD}).status_code == 404
