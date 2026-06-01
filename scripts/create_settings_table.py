"""
Script to create the app_settings table for environment badge
"""
from app import create_app, db
from app.settings import AppSettings

app = create_app()

with app.app_context():
    # Create the app_settings table
    db.create_all()

    # Initialize default environment setting
    if not AppSettings.query.filter_by(key='environment').first():
        AppSettings.set_setting('environment', 'dev', 'system')
        print("Default environment setting initialized to 'dev'")
    else:
        print("Environment setting already exists")

    print("App settings table created successfully!")
