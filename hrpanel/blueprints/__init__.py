from hrpanel.blueprints import app_upload, auth, dashboard, employees, first_run, pages, panel_users, profile, system


def register_blueprints(app):
    for module in (pages, auth, dashboard, employees, panel_users, profile, system, app_upload, first_run):
        app.register_blueprint(module.bp)
