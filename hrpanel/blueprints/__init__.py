from hrpanel.blueprints import app_upload, auth, dashboard, employees, pages, panel_users, profile, system


def register_blueprints(app):
    for module in (pages, auth, dashboard, employees, panel_users, profile, system, app_upload):
        app.register_blueprint(module.bp)
