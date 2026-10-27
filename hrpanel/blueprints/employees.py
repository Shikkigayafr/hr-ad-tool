"""Сотрудники: создание, список, экспорт, импорт CSV, повышение, отключение/возврат, удаление, сброс пароля."""
import csv
import logging
from datetime import datetime
from io import StringIO

from flask import Blueprint, current_app, g, jsonify, make_response, request

import ad_utils
from hrpanel.employee_service import ImportFileError, create_employee, import_employees, normalize_name, template_csv
from hrpanel.extensions import db
from hrpanel.logging_config import audit
from hrpanel.security import api_login_required, api_roles_required
from hrpanel.services import iso, log_action, notify_action, scoped_employees
from hrpanel.validators import csv_safe, generate_password, password_error
from models import Employee

bp = Blueprint("employees", __name__)
log = logging.getLogger("hrpanel")

ROLE_LABELS = {"Sbis_Stager": "Стажер", "Sbis_Main": "Основной", "Sbis_Senior": "Старший"}


def serialize_employee(e):
    return {"id": e.id, "full_name": e.full_name, "role": e.role, "department": e.department,
            "created_at": iso(e.created_at), "is_active": e.is_active,
            "disabled_at": iso(e.disabled_at), "disabled_reason": e.disabled_reason}


def get_scoped_employee(emp_id):
    """Сотрудник в пределах прав текущего пользователя или (None, ответ 404)."""
    emp = scoped_employees().filter(Employee.id == emp_id).first()
    if not emp:
        return None, (jsonify({"ok": False, "message": "Не найден"}), 404)
    return emp, None


def hr_stagers_only(emp, action):
    """HR работает только со стажёрами. Возвращает ответ-отказ или None."""
    if g.user.role == "hr" and emp.role != "Sbis_Stager":
        return jsonify({"ok": False, "message": f"HR {action} только стажёров"}), 403
    return None


@bp.route("/api/employees", methods=["GET"])
@api_login_required
def get_employees():
    emps = scoped_employees().order_by(Employee.full_name).all()
    return jsonify({"ok": True, "employees": [serialize_employee(e) for e in emps]})


@bp.route("/api/employees/export", methods=["GET"])
@api_login_required
def export_employees():
    emps = scoped_employees().order_by(Employee.id).all()
    si = StringIO()
    si.write("﻿")
    cw = csv.writer(si, delimiter=";")
    cw.writerow(["ID", "ФИО", "Логин", "Отдел", "Роль", "Статус", "Дата создания"])
    for emp in emps:
        created = emp.created_at.strftime("%d.%m.%Y %H:%M") if emp.created_at else ""
        cw.writerow([emp.id, csv_safe(emp.full_name), csv_safe(emp.login), csv_safe(emp.department),
                     ROLE_LABELS.get(emp.role, emp.role), "Работает" if emp.is_active else "Отключён", created])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=employees_export.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output


@bp.route("/api/create", methods=["POST"])
@api_login_required
def create():
    data = request.get_json(silent=True) or {}
    ok, message, status = create_employee(
        full_name=normalize_name(data.get("full_name")),
        login=str(data.get("login") or "").strip(),
        email=str(data.get("email") or "").strip(),
        password=str(data.get("password") or ""),
        department=data.get("department"),
        role=data.get("role", "Sbis_Stager"),
        confirm=str(data.get("confirm") or ""),
    )
    return jsonify({"ok": ok, "message": message}), status


# --- Массовый импорт из CSV ---
@bp.route("/api/employees/import/template", methods=["GET"])
@api_login_required
def import_template():
    output = make_response(template_csv())
    output.headers["Content-Disposition"] = "attachment; filename=employees_import_template.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output


@bp.route("/api/employees/import", methods=["POST"])
@api_login_required
def import_csv():
    """multipart: file=<CSV>. ?dry_run=1 — только проверить, ничего не создавая."""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "message": "Файл не выбран"}), 400
    dry_run = request.args.get("dry_run", "0") in ("1", "true", "yes")
    try:
        result = import_employees(file.read(), dry_run=dry_run)
    except ImportFileError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"  # в ответе могут быть сгенерированные пароли
    return response


# --- Повышение ---
@bp.route("/api/employee/<int:emp_id>/promote", methods=["POST"])
@api_roles_required("admin", "manager")
def promote_employee(emp_id):
    emp, error = get_scoped_employee(emp_id)
    if error:
        return error
    if not emp.is_active:
        return jsonify({"ok": False, "message": "Сотрудник отключён"}), 400
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


# --- Отключение вместо удаления ---
@bp.route("/api/employee/<int:emp_id>/disable", methods=["POST"])
@api_login_required
def disable_employee(emp_id):
    """Увольнение: учётка отключается (в AD — ещё и уезжает в OU Disabled), но не удаляется."""
    emp, error = get_scoped_employee(emp_id)
    if error:
        return error
    denied = hr_stagers_only(emp, "отключает")
    if denied:
        return denied
    if not emp.is_active:
        return jsonify({"ok": False, "message": "Сотрудник уже отключён"}), 400

    reason = str((request.get_json(silent=True) or {}).get("reason") or "").strip()[:100]

    if current_app.config["AD_SYNC_CHANGES"]:
        ok, message = ad_utils.disable_user(emp.login, reason, group_dn=ad_utils.get_group_dn(emp.role))
        if not ok:
            return jsonify({"ok": False, "message": message}), 500

    emp.is_active = False
    emp.disabled_at = datetime.utcnow()
    emp.disabled_reason = reason or None
    text = f"отключил сотрудника {emp.full_name}" + (f" ({reason})" if reason else "")
    log_action(text)
    db.session.commit()
    notify_action(text)
    audit("employee_disabled", login=emp.login, reason=reason)
    return jsonify({"ok": True, "message": "Сотрудник отключён"})


@bp.route("/api/employee/<int:emp_id>/enable", methods=["POST"])
@api_login_required
def enable_employee(emp_id):
    """Возврат отключённого сотрудника (ошибочное увольнение, выход из отпуска и т.п.)."""
    emp, error = get_scoped_employee(emp_id)
    if error:
        return error
    denied = hr_stagers_only(emp, "возвращает")
    if denied:
        return denied
    if emp.is_active:
        return jsonify({"ok": False, "message": "Сотрудник и так работает"}), 400

    if current_app.config["AD_SYNC_CHANGES"]:
        ok, message = ad_utils.enable_user(emp.login, emp.department, group_dn=ad_utils.get_group_dn(emp.role))
        if not ok:
            return jsonify({"ok": False, "message": message}), 500

    emp.is_active = True
    emp.disabled_at = None
    emp.disabled_reason = None
    text = f"вернул сотрудника {emp.full_name}"
    log_action(text)
    db.session.commit()
    notify_action(text)
    audit("employee_enabled", login=emp.login)
    return jsonify({"ok": True, "message": "Сотрудник возвращён"})


@bp.route("/api/employee/<int:emp_id>", methods=["DELETE"])
@api_roles_required("admin")
def delete_employee(emp_id):
    """Окончательное удаление — только админ и только для уже отключённых."""
    emp, error = get_scoped_employee(emp_id)
    if error:
        return error
    if emp.is_active:
        return jsonify({"ok": False, "message": "Сначала отключите сотрудника"}), 409

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
    emp, error = get_scoped_employee(emp_id)
    if error:
        return error
    denied = hr_stagers_only(emp, "сбрасывает пароль")
    if denied:
        return denied
    if not emp.is_active:
        return jsonify({"ok": False, "message": "Сотрудник отключён"}), 400
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
