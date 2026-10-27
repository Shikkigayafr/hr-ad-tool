from hrpanel.blueprints import auth, dashboard, employees, pages, panel_users, profile, system


def register_blueprints(app):
    for module in (pages, auth, dashboard, employees, panel_users, profile, system):
        app.register_blueprint(module.bp)
