from flask import Blueprint, jsonify

bp = Blueprint("system", __name__)


@bp.route("/health")
def health_check():
    # Простой ответ, что сервер жив (используется Docker healthcheck)
    return jsonify({"status": "ok"}), 200
