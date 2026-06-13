"""
WSGI configuration for PythonAnywhere deployment.

Reads all configuration from the .env file in the project root.
To generate a SECRET_KEY:
    python -c 'import secrets; print(secrets.token_hex(32))'
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
# PATH CONFIGURATION
# ============================================================

PYTHONANYWHERE_USERNAME = 'alvinccruz'
project_home = f'/home/{PYTHONANYWHERE_USERNAME}/cas'

if project_home not in sys.path:
    sys.path.insert(0, project_home)

# ============================================================
# LOAD ENVIRONMENT — .env is the single source of truth
# ============================================================

# Load .env using absolute path so it works regardless of WSGI CWD
load_dotenv(Path(project_home) / '.env')

# ============================================================
# APPLICATION INITIALIZATION
# ============================================================

from app import create_app
from werkzeug.middleware.proxy_fix import ProxyFix

application = create_app()

# Trust PythonAnywhere's reverse proxy headers so Flask correctly detects HTTPS
# Without this, enforce_https() redirects every HTTPS request in an infinite loop
application.wsgi_app = ProxyFix(application.wsgi_app, x_proto=1, x_host=1)
