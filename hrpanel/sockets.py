"""Socket.IO: события журнала получают только те, кто имеет право их видеть."""
from flask import session
from flask_socketio import join_room

from hrpanel.extensions import db, socketio
from models import User


@socketio.on("connect")
def on_connect():
    uid = session.get("user_id")
    user = db.session.get(User, uid) if uid else None
    if not user:
        return False  # неавторизованных не пускаем
    if user.role == "admin": join_room("role:admin")
    if user.role == "hr" and user.department: join_room(f"hr:{user.department}")
    if user.role == "manager" and user.department: join_room(f"manager:{user.department}")
