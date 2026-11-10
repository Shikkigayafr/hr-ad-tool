"""Socket.IO: события журнала получают только те, кто имеет право их видеть."""
from flask import request, session
from flask_socketio import join_room

from hrpanel.extensions import db, socketio
from hrpanel.metrics import WS_CLIENTS
from hrpanel.security import session_auth_tag, session_matches_user
from models import User

# sid подключённых клиентов: gauge считает по набору, поэтому не «уплывает» при обрывах
_connected = {}
WS_CLIENTS.set_function(lambda: len(_connected))


@socketio.on("connect")
def on_connect():
    uid = session.get("user_id")
    user = db.session.get(User, uid) if uid else None
    if not session_matches_user(user) or user.must_change_password:
        return False  # неавторизованных не пускаем
    _connected[request.sid] = (user.id, session_auth_tag(user), user.role, user.department, session.get("csrf"))
    if user.role == "admin": join_room("role:admin")
    if user.role == "hr" and user.department: join_room(f"hr:{user.department}")
    if user.role == "manager" and user.department: join_room(f"manager:{user.department}")


@socketio.on("disconnect")
def on_disconnect(*_args):
    _connected.pop(request.sid, None)


def disconnect_user(user_id, csrf=None):
    """Отзываем сокеты после выхода, удаления или смены пароля (один worker)."""
    for sid, state in list(_connected.items()):
        if state[0] == user_id and (csrf is None or state[4] == csrf):
            socketio.server.disconnect(sid, namespace="/")
            _connected.pop(sid, None)


def prune_connections():
    """Перед рассылкой сверяем права с БД: старые комнаты не должны раскрывать события."""
    for sid, state in list(_connected.items()):
        user = db.session.get(User, state[0], populate_existing=True)
        if (not user or user.must_change_password
                or state[1:4] != (session_auth_tag(user), user.role, user.department)):
            socketio.server.disconnect(sid, namespace="/")
            _connected.pop(sid, None)
