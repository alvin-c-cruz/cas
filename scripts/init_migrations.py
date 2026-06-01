"""
Script to initialize Flask-Migrate
"""
import os
import sys

# Set FLASK_APP environment variable
os.environ['FLASK_APP'] = 'flask_app.py'

# Import flask and flask_migrate
from flask.cli import FlaskGroup
from app import create_app, db

# Create app
app = create_app()

# Import all models to ensure they're registered
from app.users.models import User, LoginHistory
from app.accounts.models import Account
from app.branches.models import Branch
from app.settings import AppSettings

if __name__ == '__main__':
    print("Initializing Flask-Migrate...")
    print("\nTo use Flask-Migrate, run these commands:")
    print("1. flask db init              # Initialize migrations (first time only)")
    print("2. flask db migrate -m 'msg'  # Create a new migration")
    print("3. flask db upgrade           # Apply migrations")
    print("4. flask db downgrade         # Rollback migrations")
    print("\nNote: Set FLASK_APP=flask_app.py environment variable before running flask commands")
