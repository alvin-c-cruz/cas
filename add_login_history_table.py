"""
Script to add login_history table to existing database
"""
from app import create_app, db
from app.users.models import LoginHistory

app = create_app()

with app.app_context():
    # Create only the login_history table
    db.create_all()
    print("Login history table created successfully!")
