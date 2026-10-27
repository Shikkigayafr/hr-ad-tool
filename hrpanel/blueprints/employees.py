"""Сотрудники: создание, список, экспорт, повышение, удаление и сброс пароля."""
import csv
import logging
from io import StringIO

from flask import Blueprint, current_app, g, jsonify, make_response, request

import ad_utils
from hrpanel.extensions import db
from hrpanel.logging_config import audit
from hrpanel.security import api_login_required, api_roles_required
from hrpanel.services import (DEPARTMENTS, EMPLOYEE_ROLES, iso, log_action, notify_action, scoped_employees)
from hrpanel.validators import EMAIL_RE, LOGIN_RE, NAME_RE, csv_safe, generate_password, password_error
from models import Employee

bp = Blueprint("employees", __name__)
log = logging.getLogger("hrpanel")


@bp.route("/api/employees", methods=["GET"])
@api_login_required
def get_employees():
    emps = scoped_employees().order_by(Employee.full_name).all()
    return jsonify({"ok": True, "employees": [{
        "id": e.id, "full_name": e.full_name, "role": e.role,
        "department": e.department, "created_at": iso(e.created_at),
    } for e in emps]})


@bp.route("/api/employees/export", methods=["GET"])
@api_login_required
def export_employees():
    emps = scoped_employees().order_by(Employee.id).all()
    si = StringIO()
    si.write("﻿")
    cw = csv.writer(si, delimiter=";")
    cw.writerow(["ID", "ФИО", "Логин", "Отдел", "Роль", "Дата создания"])
    roles = {"Sbis_Stager": "Стажер", "Sbis_Main": "Основной", "Sbis_Senior": "Старший"}
    for emp in emps:
        created = emp.created_at.strftime("%d.%m.%Y %H:%M") if emp.created_at else ""
        cw.writerow([emp.id, csv_safe(emp.full_name), csv_safe(emp.login), csv_safe(emp.department),
                     roles.get(emp.role, emp.role), created])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=employees_export.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output


@bp.route("/api/create", methods=["POST"])
@api_login_required
def create():
    data = request.get_json(silent=True) or {}
    full_name = " ".join(str(data.get("full_name") or "").split())
    login = str(data.get("login") or "").strip()
    email = str(data.get("email") or "").strip()
    password = str(data.get("password") or "")
    confirm = str(data.get("confirm") or "")
    department = data.get("department")
    selected_role = data.get("role", "Sbis_Stager")

    if not full_name or not login or not password or not department:
        return jsonify({"ok": False, "message": "Заполните все поля"}), 400
    if len(full_name) < 3 or len(full_name) > 150 or not NAME_RE.match(full_name):
        return jsonify({"ok": False, "message": "ФИО: от 3 до 150 символов, только буквы, пробелы, точки и дефисы"}), 400
    if not LOGIN_RE.match(login):
        return jsonify({"ok": False, "message": "Логин: от 3 до 20 символов (латиница, цифры, точки, дефисы)"}), 400
    if email and not EMAIL_RE.match(email):
        return jsonify({"ok": False, "message": "Некорректный email"}), 400
    if password != confirm:
        return jsonify({"ok": False, "message": "Пароли не совпадают"}), 400
    err = password_error(password)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    if department not in DEPARTMENTS:
        return jsonify({"ok": False, "message": "Неизвестный отдел"}), 400
    if selected_role not in EMPLOYEE_ROLES:
        return jsonify({"ok": False, "message": "Неизвестная роль"}), 400

    if g.user.role != "admin" and department != g.user.department:
        return jsonify({"ok": False, "message": "Нет прав на этот отдел"}), 403
    if g.user.role != "admin" and selected_role == "Sbis_Senior":
        return jsonify({"ok": False, "message": "Только админ может создавать Старших"}), 403

    if Employee.query.filter(db.func.lower(Employee.login) == login.lower()).first():
        return jsonify({"ok": False, "message": "Сотрудник с таким логином уже есть"}), 409

    try:
        ok, message = ad_utils.create_user(full_name, login, password, department=department,
                                           group_dn=ad_utils.get_group_dn(selected_role), email=email or None)
    except Exception as e:
        log.exception("Ошибка связи с AD при создании %s", login)
        ok, message = False, f"Ошибка связи с AD: {e}"

    if ok:
        db.session.add(Employee(full_name=full_name, login=login, department=department, role=selected_role))
        text = f"создал сотрудника {full_name}"
        log_action(text)
        db.session.commit()
        notify_action(text)
        audit("employee_created", login=login, department=department, role=selected_role)

        if current_app.config["SABY_ENABLED"]:
            # Saby не критичен: ошибка не отменяет создание в AD
            try:
                from saby_utils import create_saby_user
                saby_ok, saby_msg = create_saby_user(full_name, login, password, department)
            except Exception as e:
                log.exception("Ошибка Saby при создании %s", login)
                saby_ok, saby_msg = False, f"Ошибка Saby: {e}"
            audit("saby_create", login=login, ok=saby_ok)
            message += f" | Saby: {saby_msg}"
    else:
        audit("employee_create_failed", login=login, department=department)

    return jsonify({"ok": ok, "message": message}), (200 if ok else 500)


@bp.route("/api/employee/<int:emp_id>/promote", methods=["POST"])
@api_roles_required("admin", "manager")
def promote_employee(emp_id):
    emp = scoped_employees().filter(Employee.id == emp_id).first()
    if not emp:
        return jsonify({"ok": False, "message": "Не найден"}), 404
    if emp.role != "Sbis_Stager":
        return jsonify({"ok": False, "message": "Уже не стажер"}), 400

    if current_app.config["AD_SYNC_CHANGES"]:
        ok, message = ad_utils.change_group(emp.login, from_group_dn=ad_utils.get_group_dn("Sbis_Stager"),
                                            to_group_dn=ad_utils.get_group_dn("Sbis_Main"))
        if not ok:
            return jsonify({"ok": False, "message": message}), 500

    emp.role = "Sbis_Main"
    text = f"повысил сотрудника {emp.full_name}"
    log_action(text)
    db.session.commit()
    notify_action(text)
    audit("employee_promoted", login=emp.login)
    return jsonify({"ok": True, "message": "Повышен"})


@bp.route("/api/employee/<int:emp_id>", methods=["DELETE"])
@api_login_required
def delete_employee(emp_id):
    emp = scoped_employees().filter(Employee.id == emp_id).first()
    if not emp:
        return jsonify({"ok": False, "message": "Не найден"}), 404
    if g.user.role == "hr" and emp.role != "Sbis_Stager":
        return jsonify({"ok": False, "message": "HR удаляет только стажеров"}), 403

    if current_app.config["AD_SYNC_CHANGES"]:
        ok, message = ad_utils.delete_user(emp.login)
        if not ok:
            return jsonify({"ok": False, "message": message}), 500

    text = f"удалил сотрудника {emp.full_name}"
    login = emp.login
    log_action(text)
    db.session.delete(emp)
    db.session.commit()
    notify_action(text)
    audit("employee_deleted", login=login)
    return jsonify({"ok": True, "message": "Удален"})


@bp.route("/api/employee/<int:emp_id>/reset-password", methods=["POST"])
@api_roles_required("admin", "hr", "manager")
def reset_employee_password(emp_id):
    """Сброс пароля сотрудника в AD. Пароль можно задать, иначе он генерируется и
    возвращается ОДИН раз (в базу и в логи он не пишется)."""
    emp = scoped_employees().filter(Employee.id == emp_id).first()
    if not emp:
        return jsonify({"ok": False, "message": "Не найден"}), 404
    if g.user.role == "hr" and emp.role != "Sbis_Stager":
        return jsonify({"ok": False, "message": "HR сбрасывает пароль только стажёрам"}), 403
    if not (current_app.config["AD_SYNC_CHANGES"] or ad_utils.DRY_RUN):
        return jsonify({"ok": False, "message": "Изменения в AD выключены (AD_SYNC_CHANGES=false)"}), 503

    password = str((request.get_json(silent=True) or {}).get("password") or "")
    if password:
        err = password_error(password)
        if err:
            return jsonify({"ok": False, "message": err}), 400
    else:
        password = generate_password()

    try:
        ok, message = ad_utils.reset_password(emp.login, password, must_change=True)
    except Exception as e:
        log.exception("Ошибка связи с AD при сбросе пароля %s", emp.login)
        ok, message = False, f"Ошибка связи с AD: {e}"
    if not ok:
        audit("password_reset_failed", login=emp.login)
        return jsonify({"ok": False, "message": message}), 500

    text = f"сбросил пароль сотруднику {emp.full_name}"
    log_action(text)
    db.session.commit()
    notify_action(text)
    audit("password_reset", login=emp.login)

    response = jsonify({"ok": True, "password": password,
                        "message": "Пароль сброшен. При первом входе сотрудник должен будет его сменить."})
    response.headers["Cache-Control"] = "no-store"
    return response
