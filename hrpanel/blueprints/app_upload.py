from flask import Blueprint, current_app, g, jsonify, render_template, request

from hrpanel.app_upload import MAX_INSTALLER_SIZE, installation_command, publish_installer, validate_installer
from hrpanel.config import env_bool
from hrpanel.extensions import db
from hrpanel.logging_config import audit
from hrpanel.security import api_roles_required, client_ip, login_lock_seconds, page_login_required
from models import LoginHistory

bp = Blueprint('app_upload', __name__)


@bp.get('/app-upload')
@page_login_required('admin')
def page():
    return render_template('app_upload.html', enabled=env_bool('APP_UPLOAD_ENABLED'))


@bp.post('/api/app-upload')
@api_roles_required('admin')
def upload():
    if not env_bool('APP_UPLOAD_ENABLED'):
        return jsonify(ok=False, message='Загрузка приложений отключена'), 503
    ip = client_ip()
    username = g.user.username
    if login_lock_seconds(ip, username):
        return jsonify(ok=False, message='Слишком много попыток. Попробуйте позже.'), 429
    request.max_content_length = MAX_INSTALLER_SIZE + 1024 * 1024
    if not g.user.check_password(request.form.get('admin_password', '')):
        db.session.add(LoginHistory(username=username, ip_address=ip, success=False))
        db.session.commit()
        audit('app_upload_auth_failed')
        return jsonify(ok=False, message='Неверный пароль администратора'), 403

    package = request.files.get('installer')
    if not package or request.form.get('confirm_publish') != 'yes':
        return jsonify(ok=False, message='Выберите файл и подтвердите публикацию'), 400
    name = request.form.get('publish_name', '').strip() or package.filename
    if name.rsplit('.', 1)[-1].lower() != package.filename.rsplit('.', 1)[-1].lower():
        return jsonify(ok=False, message='Расширение имени публикации должно совпадать с файлом'), 400
    try:
        command = installation_command(name, request.form.get('arguments', '').strip())
        size = validate_installer(package.stream, name)
        publish_installer(package.stream, name, command, size)
    except ValueError as error:
        return jsonify(ok=False, message=str(error)), 400
    except FileExistsError as error:
        return jsonify(ok=False, message=str(error)), 409
    except Exception as error:
        current_app.logger.warning('Ошибка публикации приложения: %s', type(error).__name__)
        audit('app_upload_failed', package=name)
        return jsonify(ok=False, message='Публикация прервалась. Проверьте обе папки и батник перед повтором.'), 502
    audit('app_uploaded', package=name, size=size)
    return jsonify(ok=True, message='Файл добавлен в обе папки, батник SYSVOL дополнен', command=command), 201
