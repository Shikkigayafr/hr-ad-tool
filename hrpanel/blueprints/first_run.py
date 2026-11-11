from threading import Lock
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session, url_for
from ldap3.core.exceptions import LDAPException

from hrpanel.domain_setup import apply_settings, check_connection, parse_settings, save_settings
from hrpanel.extensions import db
from hrpanel.logging_config import audit
from hrpanel.security import api_roles_required, page_login_required
from hrpanel.validators import password_error

bp = Blueprint('first_run', __name__)
_setup_lock = Lock()


def local_setup_host():
    try:
        return urlsplit('//' + request.host).hostname in {'127.0.0.1', 'localhost', '::1'}
    except ValueError:
        return False


@bp.get('/setup')
@page_login_required('admin')
def page():
    if not g.user.setup_required:
        return redirect(url_for('pages.index'))
    return render_template('first_run.html', local_access=local_setup_host())


@bp.post('/api/setup')
@api_roles_required('admin')
def finish():
    if not local_setup_host() or not g.user.setup_required:
        return jsonify(ok=False, message='Первичная настройка доступна только при первом входе через localhost'), 403
    data = request.get_json(silent=True) or {}
    password = data.get('new_password')
    if not isinstance(password, str) or len(password) > 1024:
        return jsonify(ok=False, message='Укажите новый пароль администратора'), 400
    error = password_error(password)
    if error:
        return jsonify(ok=False, message=error), 400
    if password != data.get('confirm_password'):
        return jsonify(ok=False, message='Пароли не совпадают'), 400
    if not _setup_lock.acquire(blocking=False):
        return jsonify(ok=False, message='Настройка уже выполняется'), 409
    try:
        db.session.refresh(g.user)
        if not g.user.setup_required:
            return jsonify(ok=False, message='Первичная настройка уже завершена'), 409
        settings = parse_settings(data)
        check_connection(settings)
        save_settings(current_app, settings)
        g.user.set_password(password)
        g.user.setup_required = False
        g.user.must_change_password = False
        db.session.commit()
        apply_settings(current_app, settings)
        audit('first_run_completed')
        session.clear()
        return jsonify(ok=True)
    except ValueError as exc:
        return jsonify(ok=False, message=str(exc)), 400
    except (LDAPException, OSError):
        return jsonify(ok=False, message='Проверьте доступность LDAPS, сертификат CA и права на каталог instance'), 502
    except RuntimeError as exc:
        return jsonify(ok=False, message=str(exc)), 503
    finally:
        _setup_lock.release()
