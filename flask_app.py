"""
CAS (Computerized Accounting System) - Flask Application Entry Point

CAS is a general-purpose, industry-agnostic accounting system for
Philippine SMEs (BIR-compliant), used by multiple companies across
different industries. Sample/demo data may use industry-flavored names
(e.g., construction suppliers), but these are illustrative only.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env relative to this file so it works under WSGI (CWD is unpredictable).
# load_dotenv never overrides variables already in the process environment, so a
# launcher that exports SQLALCHEMY_DATABASE_URI / FLASK_PORT wins over .env.
load_dotenv(Path(__file__).parent / '.env')

from app import create_app

# Create app with environment-based configuration
env = os.environ.get('FLASK_ENV', 'development')
app = create_app(config_name=env)


def _guard_company(flask_app):
    """Refuse to run against a database that belongs to a different company.

    Several companies share this codebase on separate SQLite files. When the
    launcher sets CAS_EXPECT_COMPANY ('philgen' / 'ric'), the label is checked
    against the company_name stored INSIDE the database, so a process started
    against the wrong file dies loudly instead of quietly touching the other
    company's books. Runs at import so `flask db upgrade` is guarded exactly
    like the dev server. Unset -> no check (plain `python flask_app.py` still
    works and just prints the banner).
    """
    expected = os.environ.get('CAS_EXPECT_COMPANY')
    if not expected:
        return
    from app.utils.company_guard import company_mismatch
    with flask_app.app_context():
        reason = company_mismatch(expected)
    if reason:
        print(f"REFUSING TO START: {reason}", file=sys.stderr, flush=True)
        sys.exit(2)


_guard_company(app)


def _announce(flask_app, port):
    """Say which database and company this dev server is about to serve."""
    from app.settings import AppSettings

    with flask_app.app_context():
        try:
            company = AppSettings.get_setting('company_name') or '(not set)'
        except Exception:  # noqa: BLE001 - unmigrated/empty DB; banner must still print
            company = '(unreadable)'

    expected = os.environ.get('CAS_EXPECT_COMPANY')
    bar = '=' * 72
    print(bar)
    print(f"  CAS dev server  ->  http://127.0.0.1:{port}")
    print(f"  Company : {company}")
    print(f"  Database: {flask_app.config.get('SQLALCHEMY_DATABASE_URI', '')}")
    print(f"  Guard   : {expected or 'OFF (set CAS_EXPECT_COMPANY, or launch via cas.ps1)'}")
    print(bar, flush=True)


if __name__ == '__main__':
    # Get debug mode from config (already set from .env)
    debug_mode = app.config.get('DEBUG', False)
    port = int(os.environ.get('FLASK_PORT', 5050))
    _announce(app, port)
    # use_reloader=False: keep the interactive debugger/tracebacks (debug_mode) but
    # do NOT auto-restart the server when code under app/ is edited. Editing the
    # codebase no longer bounces the running process — restart manually to pick up
    # .py changes (templates still reload live per Jinja).
    app.run(debug=debug_mode, port=port, use_reloader=False)
