from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from datetime import datetime

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app(config=None):
    """Application factory pattern"""
    app = Flask(__name__)

    # Make datetime available in templates (Philippine Standard Time)
    @app.context_processor
    def inject_now():
        from app.utils import ph_now
        return {'now': ph_now()}

    # Default configuration
    app.config['SECRET_KEY'] = config.get('SECRET_KEY', 'your-secret-key-here') if config else 'your-secret-key-here'
    app.config['SQLALCHEMY_DATABASE_URI'] = config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///cas.db') if config else 'sqlite:///cas.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions
    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = 'users.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from app.users.models import User
        return User.query.get(int(user_id))

    # Import models for migrations (must be before migrate.init_app)
    from app.accounts.models import Account
    from app.accounts.approval_models import AccountChangeRequest
    from app.users.models import User, LoginHistory
    from app.branches.models import Branch
    from app.vendors.models import Vendor
    from app.settings import AppSettings

    # Register blueprints
    from app.dashboard.views import dashboard_bp
    from app.accounts.views import accounts_bp
    from app.users.views import users_bp
    from app.api.views import api_bp
    from app.branches.views import branches_bp
    from app.vendors.views import vendors_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp, url_prefix='/accounts')
    app.register_blueprint(users_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(branches_bp)
    app.register_blueprint(vendors_bp)


    migrate.init_app(app, db)


    return app
