"""Точка входа: `gunicorn app:app`, `flask --app app ...`, `python app.py`.
Вся логика живёт в пакете hrpanel/ (см. hrpanel/__init__.py)."""
from dotenv import load_dotenv

load_dotenv()

from hrpanel import create_app  # noqa: E402
from hrpanel.extensions import socketio  # noqa: E402

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
