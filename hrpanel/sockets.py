"""Socket.IO: события журнала получают только те, кто имеет право их видеть."""
from flask import request, session
from flask_socketio import join_room

from hrpanel.extensions import db, socketio
from hrpanel.metrics import WS_CLIENTS
from models import User

# sid подключённых клиентов: gauge считает по набору, поэтому не «уплывает» при обрывах
_connected = set()
WS_CLIENTS.set_function(lambda: len(_connected))


@socketio.on("connect")
def on_connect():
    uid = session.get("user_id")
    user = db.session.get(User, uid) if uid else None
    if not user:
        return False  # неавторизованных не пускаем
    _connected.add(request.sid)
    if user.role == "admin": join_room("role:admin")
    if user.role == "hr" and user.department: join_room(f"hr:{user.department}")
    if user.role == "manager" and user.department: join_room(f"manager:{user.department}")


@socketio.on("disconnect")
def on_disconnect(*_args):
    _connected.discard(request.sid)
