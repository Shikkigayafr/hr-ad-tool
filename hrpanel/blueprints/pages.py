from flask import Blueprint, render_template

from hrpanel.security import page_login_required
from hrpanel.services import DEPARTMENTS
from models import Employee

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/create")
@page_login_required()
def page_create():
    return render_template("create.html", departments=DEPARTMENTS)


@bp.route("/import")
@page_login_required()
def page_import():
    return render_template("import.html")


@bp.route("/employees")
@page_login_required()
def page_employees():
    return render_template("employees.html")


@bp.route("/profile")
@page_login_required()
def page_profile():
    return render_template("profile.html")


@bp.route("/logs")
@page_login_required()
def page_logs():
    return render_template("logs.html")


@bp.route("/users")
@page_login_required("admin")
def page_users():
    return render_template("users.html", departments=DEPARTMENTS)


@bp.get("/employee-data")
@page_login_required("admin")
def page_employee_data():
    employees = Employee.query.with_entities(
        Employee.id, Employee.full_name, Employee.login, Employee.department, Employee.is_active,
        Employee.issued_password.is_not(None).label("has_password"),
    ).order_by(Employee.full_name, Employee.id).all()
    return render_template("employee_data.html", employees=employees)
