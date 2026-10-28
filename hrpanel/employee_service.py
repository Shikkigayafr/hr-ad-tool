"""Создание сотрудников: общая логика для формы /create и массового импорта из CSV."""
import csv
import io
import logging

from flask import current_app, g

import ad_utils
from hrpanel.extensions import db
from hrpanel.integrations import call_ad, call_saby, call_yandex
from hrpanel.logging_config import audit
from hrpanel.services import DEPARTMENTS, EMPLOYEE_ROLES, log_action, notify_action
from hrpanel.validators import EMAIL_RE, LOGIN_RE, NAME_RE, generate_password, password_error
from models import Employee

log = logging.getLogger("hrpanel")

MAX_IMPORT_ROWS = 200

# Заголовки CSV (регистр не важен) -> внутренние поля
COLUMN_ALIASES = {
    "фио": "full_name", "full_name": "full_name", "name": "full_name",
    "логин": "login", "login": "login",
    "email": "email", "почта": "email", "e-mail": "email",
    "отдел": "department", "department": "department",
    "роль": "role", "role": "role",
    "пароль": "password", "password": "password",
}
ROLE_ALIASES = {
    "стажер": "Sbis_Stager", "стажёр": "Sbis_Stager", "sbis_stager": "Sbis_Stager",
    "основной": "Sbis_Main", "sbis_main": "Sbis_Main",
    "старший": "Sbis_Senior", "sbis_senior": "Sbis_Senior",
}
TEMPLATE_HEADER = ["ФИО", "Логин", "Email", "Отдел", "Роль", "Пароль"]


def normalize_name(raw) -> str:
    return " ".join(str(raw or "").split())


def check_new_employee(full_name, login, email, password, department, role, confirm=None):
    """Проверки перед созданием. Возвращает (сообщение, http-статус) или None, если всё в порядке."""
    if not full_name or not login or not password or not department:
        return "Заполните все поля", 400
    if len(full_name) < 3 or len(full_name) > 150 or not NAME_RE.match(full_name):
        return "ФИО: от 3 до 150 символов, только буквы, пробелы, точки и дефисы", 400
    if not LOGIN_RE.match(login):
        return "Логин: от 3 до 20 символов (латиница, цифры, точки, дефисы)", 400
    if email and not EMAIL_RE.match(email):
        return "Некорректный email", 400
    if confirm is not None and password != confirm:
        return "Пароли не совпадают", 400
    err = password_error(password)
    if err:
        return err, 400
    if department not in DEPARTMENTS:
        return "Неизвестный отдел", 400
    if role not in EMPLOYEE_ROLES:
        return "Неизвестная роль", 400

    if g.user.role != "admin" and department != g.user.department:
        return "Нет прав на этот отдел", 403
    if g.user.role != "admin" and role == "Sbis_Senior":
        return "Только админ может создавать Старших", 403

    if Employee.query.filter(db.func.lower(Employee.login) == login.lower()).first():
        return "Сотрудник с таким логином уже есть", 409
    return None


def create_employee(full_name, login, email, password, department, role, confirm=None):
    """Создаёт сотрудника в AD (и в Saby, если включено), затем в БД панели.
    Возвращает (ok, сообщение, http-статус)."""
    problem = check_new_employee(full_name, login, email, password, department, role, confirm)
    if problem:
        return False, problem[0], problem[1]

    try:
        ok, message = call_ad("create_user", ad_utils.create_user, full_name, login, password, department=department,
                              group_dn=ad_utils.get_group_dn(role), email=email or None)
    except Exception as e:
        log.exception("Ошибка связи с AD при создании %s", login)
        ok, message = False, f"Ошибка связи с AD: {e}"

    if not ok:
        audit("employee_create_failed", login=login, department=department)
        return False, message, 500

    db.session.add(Employee(full_name=full_name, login=login, department=department, role=role))
    text = f"создал сотрудника {full_name}"
    log_action(text)
    db.session.commit()
    notify_action(text)
    audit("employee_created", login=login, department=department, role=role)

    if current_app.config["SABY_ENABLED"]:
        # Saby не критичен: ошибка не отменяет создание в AD
        try:
            from saby_utils import create_saby_user
            saby_ok, saby_msg = call_saby("create_user", create_saby_user, full_name, login, password, department)
        except Exception as e:
            log.exception("Ошибка Saby при создании %s", login)
            saby_ok, saby_msg = False, f"Ошибка Saby: {e}"
        audit("saby_create", login=login, ok=saby_ok)
        message += f" | Saby: {saby_msg}"

    if current_app.config["YANDEX_ENABLED"]:
        # Яндекс 360 не критичен: ошибка не отменяет создание в AD
        try:
            from yandex_utils import create_yandex_user
            y_ok, y_msg = call_yandex("create_user", create_yandex_user, full_name, login, password, department)
        except Exception as e:
            log.exception("Ошибка Яндекс 360 при создании %s", login)
            y_ok, y_msg = False, f"Ошибка Яндекс 360: {e}"
        audit("yandex_create", login=login, ok=y_ok)
        message += f" | Яндекс: {y_msg}"
    return True, message, 200


# --- Массовый импорт ---
class ImportFileError(ValueError):
    """Проблема с файлом целиком (кодировка, заголовки, размер)."""


def parse_import_csv(raw: bytes):
    """CSV -> список (номер_строки, {поле: значение}). Кодировка utf-8(-sig) или cp1251, разделитель ; , или таб."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1251")
        except UnicodeDecodeError:
            raise ImportFileError("Не удалось прочитать файл: сохраните его как CSV в кодировке UTF-8")
    if not text.strip():
        raise ImportFileError("Файл пустой")

    first_line = text.splitlines()[0]
    delimiter = max(";,\t", key=first_line.count) if any(d in first_line for d in ";,\t") else ";"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    header = next(reader, [])
    columns = [COLUMN_ALIASES.get(h.strip().lower()) for h in header]
    missing = [name for name in ("full_name", "login") if name not in columns]
    if missing:
        raise ImportFileError("В заголовке нужны колонки «ФИО» и «Логин» (скачайте шаблон)")

    rows = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue  # пустая строка
        rows.append((line_no, {col: cells[i].strip() for i, col in enumerate(columns) if col and i < len(cells)}))
    if not rows:
        raise ImportFileError("В файле нет данных под заголовком")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ImportFileError(f"Слишком много строк: {len(rows)} (максимум {MAX_IMPORT_ROWS} за раз)")
    return rows


def import_employees(raw: bytes, dry_run: bool):
    """Проверяет (dry_run=True) или создаёт сотрудников из CSV. Ошибка в строке не останавливает остальные."""
    rows = parse_import_csv(raw)
    results, seen_logins = [], set()

    for line_no, row in rows:
        full_name = normalize_name(row.get("full_name"))
        login = row.get("login", "").strip()
        email = row.get("email", "").strip()
        department = row.get("department", "").strip() or (g.user.department if g.user.role != "admin" else "")
        role_raw = row.get("role", "").strip().lower()
        role = ROLE_ALIASES.get(role_raw, role_raw) if role_raw else "Sbis_Stager"
        given_password = row.get("password", "")
        generated = not given_password
        password = given_password or generate_password()

        item = {"line": line_no, "full_name": full_name, "login": login, "department": department, "role": role}
        if login.lower() in seen_logins:
            item.update(ok=False, message="Логин повторяется в файле")
        else:
            seen_logins.add(login.lower())
            if dry_run:
                problem = check_new_employee(full_name, login, email, password, department, role)
                item.update(ok=problem is None, message=problem[0] if problem else "Можно создавать")
            else:
                ok, message, _ = create_employee(full_name, login, email, password, department, role)
                item.update(ok=ok, message=message)
                if ok and generated:
                    item["password"] = password  # показывается один раз, в БД и логи не пишется
        results.append(item)

    created = sum(1 for r in results if r["ok"])
    if not dry_run:
        audit("employees_imported", total=len(results), created=created, failed=len(results) - created)
    return {"ok": True, "dry_run": dry_run, "total": len(results), "created": created,
            "failed": len(results) - created, "rows": results}


def template_csv() -> str:
    """Шаблон для скачивания (с BOM, чтобы Excel не ломал кириллицу)."""
    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out, delimiter=";")
    writer.writerow(TEMPLATE_HEADER)
    writer.writerow(["Иванов Иван Иванович", "ivanov.ii", "ivanov@evostor.ru", "Офис", "Стажер", ""])
    return out.getvalue()
