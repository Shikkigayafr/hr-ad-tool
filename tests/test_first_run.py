import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from cryptography.fernet import Fernet
from werkzeug.security import check_password_hash

from hrpanel import domain_setup
from hrpanel.blueprints import first_run
from models import User, db


def test_init_db_bootstraps_only_a_fresh_database(tmp_path):
    path = tmp_path / 'first-run.db'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{path.as_posix()}'}
    env.pop('INITIAL_ADMIN_PASSWORD', None)
    env.pop('INITIAL_ADMIN_PASSWORD_FILE', None)
    cmd = [sys.executable, '-m', 'flask', '--app', 'app', 'init-db']
    root = Path(__file__).resolve().parents[1]
    subprocess.run(cmd, cwd=root, env=env, capture_output=True, check=True)
    with sqlite3.connect(path) as conn:
        username, required, hashed = conn.execute('select username, setup_required, password_hash from user').fetchone()
        assert username == 'admin' and required and check_password_hash(hashed, 'admin')
        conn.execute("update user set username='existing_admin', setup_required=0")
    subprocess.run(cmd, cwd=root, env=env, capture_output=True, check=True)
    with sqlite3.connect(path) as conn:
        assert conn.execute('select username from user').fetchall() == [('existing_admin',)]


def test_initial_admin_must_finish_setup_and_use_new_password(app, client, tmp_path, monkeypatch):
    admin = User.query.filter_by(username='admin').one()
    admin.set_password('admin')
    admin.setup_required = admin.must_change_password = True
    db.session.commit()
    monkeypatch.setenv('DOMAIN_SETUP_DIR', str(tmp_path))
    monkeypatch.setitem(app.extensions, 'employee_password_cipher', Fernet(Fernet.generate_key()))
    check = Mock(side_effect=ValueError('Проверка LDAPS не прошла'))
    apply = Mock()
    monkeypatch.setattr(first_run, 'check_connection', check)
    monkeypatch.setattr(first_run, 'apply_settings', apply)
    credentials = {'login': 'admin', 'password': 'admin'}
    assert client.post('/api/login', json=credentials, base_url='http://outside.example').status_code == 403
    assert client.post('/api/login', json=credentials).status_code == 200
    assert client.get('/').headers['Location'] == '/setup'
    assert client.get('/setup').status_code == 200
    assert client.get('/api/employees').json['code'] == 'setup_required'
    values = dict(host='dc01.corp.example', domain='corp.example', domain_user='svc@corp.example',
                  domain_password='Service-Test1!', new_password='New-Admin1!', confirm_password='New-Admin1!')
    assert client.post('/api/setup', json=values, no_csrf=True).status_code == 403
    assert client.post('/api/setup', json=values).status_code == 400
    assert not (tmp_path / 'ad-setup.enc').exists()
    check.side_effect = None
    assert client.post('/api/setup', json=values).status_code == 200
    assert values['domain_password'].encode() not in (tmp_path / 'ad-setup.enc').read_bytes()
    apply.assert_called_once()
    assert client.post('/api/login', json=credentials).status_code == 401
    assert client.post('/api/login', json={'login': 'admin', 'password': values['new_password']}).status_code == 200
    assert client.get('/api/employees').status_code == 200
    assert client.post('/api/setup', json=values).status_code == 403

    restore = Mock()
    monkeypatch.setattr(domain_setup, 'apply_settings', restore)
    domain_setup.load_settings(app)
    assert restore.call_args.args[1]['base_dn'] == 'DC=corp,DC=example'
    assert restore.call_args.args[1]['password'] == values['domain_password']
