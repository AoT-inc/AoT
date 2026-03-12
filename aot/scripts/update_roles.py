# coding=utf-8
import os
import sys

# Add the project directory to the path
sys.path.append('/opt/AoT')

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.databases.models import Role

def update_roles():
    app = create_app()
    with app.app_context():
        # Monitor role (usually ID 3)
        monitor_role = Role.query.filter_by(name='Monitor').first()
        if monitor_role:
            monitor_role.view_settings = True
            print("Updated Monitor role permissions")
        
        # Guest role (usually ID 4)
        guest_role = Role.query.filter_by(name='Guest').first()
        if guest_role:
            guest_role.view_settings = True
            print("Updated Guest role permissions")
        
        db.session.commit()
        print("Database commit successful")

if __name__ == '__main__':
    update_roles()
