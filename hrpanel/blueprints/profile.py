import os

from flask import Blueprint, current_app, g, jsonify, request

from hrpanel.extensions import db
from hrpanel.logging_config import audit
from hrpanel.security import api_login_required
from hrpanel.validators import password_error

bp = Blueprint("profile", __name__)


@bp.route("/api/profile", methods=["GET"])
@api_login_required
def get_profile():
    return jsonify({"ok": True, "username": g.user.username, "first_name": g.user.first_name,
                    "avatar": g.user.avatar, "role": g.user.role, "department": g.user.department})


@bp.route("/api/profile", methods=["POST"])
@api_login_required
def update_profile():
    new_name = str((request.get_json(silent=True) or {}).get("first_name") or "").strip()
    if not new_name:
        return jsonify({"ok": False, "message": "Имя не может быть пустым"}), 400
    if len(new_name) > 50:
        return jsonify({"ok": False, "message": "Имя слишком длинное (максимум 50 символов)"}), 400
    g.user.first_name = new_name
    db.session.commit()
    return jsonify({"ok": True, "message": "Имя успешно обновлено!"})


@bp.route("/api/profile/password", methods=["POST"])
@api_login_required
def update_password():
    data = request.get_json(silent=True) or {}
    old_pass = str(data.get("old_password") or "")
    new_pass = str(data.get("new_password") or "")
    if not old_pass or not new_pass:
        return jsonify({"ok": False, "message": "Заполните все поля"}), 400
    if not g.user.check_password(old_pass):
        return jsonify({"ok": False, "message": "Неверный текущий пароль"}), 400
    err = password_error(new_pass)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    if new_pass == old_pass:
        return jsonify({"ok": False, "message": "Новый пароль совпадает со старым"}), 400
    g.user.set_password(new_pass)
    db.session.commit()
    audit("password_changed")
    return jsonify({"ok": True, "message": "Пароль успешно изменен!"})


@bp.route("/api/profile/avatar", methods=["POST"])
@api_login_required
def upload_avatar():
    file = request.files.get("avatar")
    if not file or not file.filename:
        return jsonify({"ok": False, "message": "Файл не выбран"}), 400

    # Тип определяем по содержимому, а не по имени файла
    head = file.read(8)
    file.seek(0)
    if head.startswith(b"\x89PNG"):
        ext = "png"
    elif head.startswith(b"\xff\xd8"):
        ext = "jpg"
    else:
        return jsonify({"ok": False, "message": "Только JPG и PNG"}), 400

    upload_folder = os.path.join(current_app.root_path, "static", "avatars")
    os.makedirs(upload_folder, exist_ok=True)
    # Удаляем старый аватар с другим расширением
    for old_ext in ("png", "jpg", "jpeg"):
        old = os.path.join(upload_folder, f"user_{g.user.id}.{old_ext}")
        if old_ext != ext and os.path.exists(old):
            os.remove(old)
    filename = f"user_{g.user.id}.{ext}"
    file.save(os.path.join(upload_folder, filename))

    g.user.avatar = filename
    db.session.commit()
    return jsonify({"ok": True, "message": "Аватарка обновлена!", "filename": filename})
