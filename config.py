"""
Application configuration management
Loads configuration from environment variables for security
"""
import os
from datetime import timedelta

class Config:
    """Base configuration with security best practices"""

    # Security - Secret Key
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable must be set! "
                        "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'")

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///cas.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,  # Verify connections before using
        'pool_recycle': 3600,   # Recycle connections after 1 hour
    }

    # Session Security
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = os.environ.get('SESSION_COOKIE_HTTPONLY', 'True').lower() == 'true'
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=int(os.environ.get('PERMANENT_SESSION_LIFETIME', '43200')))

    # Security Headers
    SEND_FILE_MAX_AGE_DEFAULT = 31536000  # 1 year for static files

    # Upload Security
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', str(16 * 1024 * 1024)))  # 16MB default
    UPLOAD_FOLDER = os.environ.get(
        'UPLOAD_FOLDER',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'uploads')
    )

    # WTForms CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # No time limit (session-based)
    WTF_CSRF_SSL_STRICT = os.environ.get('WTF_CSRF_SSL_STRICT', 'False').lower() == 'true'

    # Login Security
    REMEMBER_COOKIE_SECURE = os.environ.get('REMEMBER_COOKIE_SECURE', 'False').lower() == 'true'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=7)

    # Rate Limiting (Flask-Limiter) — IP-based throttle on auth endpoints.
    # Storage is in-memory and therefore PER WORKER PROCESS: on a multi-worker
    # deployment (e.g. PythonAnywhere) each worker keeps its own counters, so the
    # effective limit is looser and resets on reload. Point RATELIMIT_STORAGE_URI
    # at a shared backend (redis://...) if/when one is available.
    RATELIMIT_ENABLED = os.environ.get('RATELIMIT_ENABLED', 'True').lower() == 'true'
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_HEADERS_ENABLED = True

    # Force any admin still on the seeded default password to change it at login.
    # Default ON everywhere except the plain testing config (which sets it False so
    # the suite's admin123 fixtures are not force-redirected). The guard's own tests
    # flip it back on locally, exactly like the rate-limit tests do (this mirrors the
    # TestingErrorsConfig pattern: config-scoped, tested where it actually fires).
    ENFORCE_DEFAULT_PW_CHANGE = os.environ.get(
        'ENFORCE_DEFAULT_PW_CHANGE', 'True').lower() == 'true'

    # Backup module — fail-closed: disabled unless explicitly enabled per instance.
    BACKUP_ENABLED = os.environ.get('BACKUP_ENABLED', 'False').lower() == 'true'
    BACKUP_STORAGE = os.environ.get('BACKUP_STORAGE', 'local')
    BACKUP_LOCAL_DIR = os.environ.get('BACKUP_LOCAL_DIR')
    BACKUP_ENC_KEY = os.environ.get('BACKUP_ENC_KEY')
    BACKUP_STALE_HOURS = int(os.environ.get('BACKUP_STALE_HOURS', '30'))
    BACKUP_LOCK_TIMEOUT_MIN = int(os.environ.get('BACKUP_LOCK_TIMEOUT_MIN', '15'))
    BACKUP_RETENTION_COUNT = int(os.environ.get('BACKUP_RETENTION_COUNT', '30'))
    # Slice 2 — Google Drive off-site (BACKUP_STORAGE=gdrive)
    BACKUP_GDRIVE_FOLDER_NAME = os.environ.get('BACKUP_GDRIVE_FOLDER_NAME', 'RIC-CAS-Backups')
    BACKUP_GDRIVE_CREDS = os.environ.get('BACKUP_GDRIVE_CREDS')   # client_secret.json path
    BACKUP_GDRIVE_TOKEN = os.environ.get('BACKUP_GDRIVE_TOKEN')   # refresh-token json path
    BACKUP_GDRIVE_TIMEOUT = int(os.environ.get('BACKUP_GDRIVE_TIMEOUT', '60'))


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False

    # In development, allow non-HTTPS
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_SSL_STRICT = False


class ProductionConfig(Config):
    """Production configuration with enhanced security"""
    DEBUG = False
    TESTING = False

    # Force HTTPS in production
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True
    ENFORCE_HTTPS = True  # Redirect HTTP to HTTPS

    # Stricter session settings
    SESSION_COOKIE_SAMESITE = 'Strict'


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = True

    # Use in-memory database for tests
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

    # Disable CSRF for testing
    WTF_CSRF_ENABLED = False

    # Disable rate limiting by default so it does not throttle the suite; the
    # dedicated rate-limit tests enable it locally (see test_login_rate_limit.py).
    RATELIMIT_ENABLED = False

    # Off in the plain testing config so the admin123 fixtures are not force-
    # redirected; the guard's own tests set it True locally.
    ENFORCE_DEFAULT_PW_CHANGE = False


class TestingErrorsConfig(TestingConfig):
    """Testing config that exercises the PRODUCTION error handlers.

    The generic 404/403/500/Exception handlers register only when DEBUG is off
    (see create_app), so plain TestingConfig (DEBUG=True) never hits them. This
    variant turns DEBUG and TESTING off and disables exception propagation so the
    test client routes errors through the handlers exactly as production would,
    while keeping the in-memory DB, CSRF-off, and no-rate-limit testing niceties.
    """
    DEBUG = False
    TESTING = False
    PROPAGATE_EXCEPTIONS = False


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'testing_errors': TestingErrorsConfig,
    'default': DevelopmentConfig
}


def get_config(env=None):
    """Get configuration object based on environment"""
    if env is None:
        env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])
