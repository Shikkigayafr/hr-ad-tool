import logging

from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from hrpanel.extensions import db

log = logging.getLogger("hrpanel")

HTTP_MESSAGES = {
    401: "Вы не авторизованы",
    404: "Не найдено",
    405: "Метод не поддерживается",
    413: "Файл слишком большой (максимум 2 МБ)",
    415: "Неверный формат запроса",
}


def register_error_handlers(app):
    @app.errorhandler(Exception)
    def handle_exception(e):
        wants_json = request.path.startswith("/api/")
        if isinstance(e, HTTPException):
            if wants_json:
                return jsonify({"ok": False, "message": HTTP_MESSAGES.get(e.code, e.description)}), e.code
            if e.code == 404:
                return render_template("404.html"), 404
            return e
        log.exception("Необработанная ошибка: %s %s", request.method, request.path)
        db.session.rollback()
        if wants_json:
            return jsonify({"ok": False, "message": "Внутренняя ошибка сервера"}), 500
        return render_template("500.html"), 500
