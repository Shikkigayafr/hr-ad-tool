import secrets

from flask import Blueprint, Response, abort, current_app, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from hrpanel.metrics import REGISTRY

bp = Blueprint("system", __name__)


@bp.route("/health")
def health_check():
    # Простой ответ, что сервер жив (используется Docker healthcheck)
    return jsonify({"status": "ok"}), 200


@bp.route("/metrics")
def metrics():
    """Метрики Prometheus. Защищены токеном; без настроенного токена эндпоинт выключен."""
    token = current_app.config.get("METRICS_TOKEN")
    if not token:
        abort(404)
    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else ""
    if not supplied or not secrets.compare_digest(supplied, token):
        return Response("Нужен заголовок Authorization: Bearer <METRICS_TOKEN>", 401,
                        {"WWW-Authenticate": "Bearer", "Content-Type": "text/plain; charset=utf-8"})
    return Response(generate_latest(REGISTRY), mimetype=CONTENT_TYPE_LATEST)
