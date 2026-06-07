"""
WSGI configuration for PythonAnywhere deployment.

This file configures the Flask application for production deployment
on PythonAnywhere using SQLite3 database.

IMPORTANT: Before deploying, update:
1. YOUR_USERNAME - Replace with your PythonAnywhere username
2. SECRET_KEY - Generate a new one and paste here

To generate SECRET_KEY:
    python -c 'import secrets; print(secrets.token_hex(32))'
"""
import sys
import os

# ============================================================
# CONFIGURATION - UPDATE THESE VALUES BEFORE DEPLOYMENT
# ============================================================

# Replace YOUR_USERNAME with your actual PythonAnywhere username
PYTHONANYWHERE_USERNAME = 'alvinccruz'

# Generate a new SECRET_KEY using the command above
# NEVER commit the real key to git - this is just a placeholder
SECRET_KEY = '9b524f3ca62046c835eb170407195b2e5723e650934989db3e3f6edf8958d0cc'

# ============================================================
# PATH CONFIGURATION (Auto-configured based on username)
# ============================================================

# Project path
project_home = f'/home/{PYTHONANYWHERE_USERNAME}/cas'

# Add project to Python path
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

# Flask secret key (for sessions, CSRF, etc.)
os.environ['SECRET_KEY'] = SECRET_KEY

# Flask environment (production mode)
os.environ['FLASK_ENV'] = 'production'

# Database URL - Not set, so config.py will use SQLite3 by default
# SQLite database will be at: /home/{username}/cas/cas.db

# ============================================================
# APPLICATION INITIALIZATION
# ============================================================

from app import create_app

# Create Flask application instance
application = create_app()

# For debugging (optional - remove in production)
# print(f"Flask app initialized for user: {PYTHONANYWHERE_USERNAME}")
# print(f"Project path: {project_home}")
# print(f"Database will be SQLite at: {project_home}/cas.db")
