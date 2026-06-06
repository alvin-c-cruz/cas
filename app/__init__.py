from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app(config=None):
    """Application factory pattern"""
    app = Flask(__name__)

    # Configure logging
    if not app.debug and not app.testing:
        # Create logs directory if it doesn't exist
        if not os.path.exists('logs'):
            os.mkdir('logs')

        # Configure file handler for all logs
        file_handler = RotatingFileHandler(
            'logs/cas_app.log',
            maxBytes=10485760,  # 10MB
            backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

        # Configure file handler for errors only
        error_handler = RotatingFileHandler(
            'logs/cas_errors.log',
            maxBytes=10485760,  # 10MB
            backupCount=10
        )
        error_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        error_handler.setLevel(logging.ERROR)
        app.logger.addHandler(error_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.info('CAS application startup')

    # Make datetime available in templates (Philippine Standard Time)
    @app.context_processor
    def inject_now():
        from app.utils import ph_now
        return {'now': ph_now()}

    # Make action items count available in all templates for sidebar badge
    @app.context_processor
    def inject_action_items_count():
        from flask_login import current_user
        count = 0
        if current_user.is_authenticated and current_user.role in ['accountant', 'admin']:
            from app.accounts.approval_models import AccountChangeRequest
            from app.vat_categories.models import VATCategoryChangeRequest
            from app.withholding_tax.models import WithholdingTaxChangeRequest

            count += AccountChangeRequest.query.filter_by(status='pending').count()
            count += VATCategoryChangeRequest.query.filter_by(status='pending').count()
            count += WithholdingTaxChangeRequest.query.filter_by(status='pending').count()

        return {'action_items_count': count}

    # Make current branch available in all templates
    @app.context_processor
    def inject_current_branch():
        from flask_login import current_user
        from flask import session
        current_branch = None
        if current_user.is_authenticated:
            branch_id = session.get('selected_branch_id')
            if branch_id:
                from app.branches.models import Branch
                current_branch = Branch.query.get(branch_id)
        return {'current_branch': current_branch}

    # Add custom Jinja2 filter for JSON parsing
    @app.template_filter('from_json')
    def from_json_filter(s):
        import json
        try:
            return json.loads(s) if s else {}
        except:
            return {}

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
    from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
    from app.withholding_tax.models import WithholdingTax, WithholdingTaxChangeRequest
    from app.customers.models import Customer
    from app.audit.models import AuditLog
    from app.notifications.models import Notification
    from app.settings import AppSettings
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
    from app.receipts.models import Receipt
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.errors.models import ErrorLog

    # Register blueprints
    from app.dashboard.views import dashboard_bp
    from app.accounts.views import accounts_bp
    from app.users.views import users_bp
    from app.api.views import api_bp
    from app.branches.views import branches_bp
    from app.vendors.views import vendors_bp
    from app.vat_categories.views import vat_categories_bp
    from app.withholding_tax.views import withholding_tax_bp
    from app.customers.views import customers_bp
    from app.audit.views import audit_bp
    from app.sales_invoices.views import sales_invoices_bp
    from app.purchase_bills.views import purchase_bills_bp
    from app.receipts.views import receipts_bp
    from app.journal_entries.views import journal_entries_bp
    from app.reports.views import reports_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp, url_prefix='/accounts')
    app.register_blueprint(users_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(branches_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(vat_categories_bp, url_prefix='/vat-categories')
    app.register_blueprint(withholding_tax_bp, url_prefix='/withholding-tax')
    app.register_blueprint(customers_bp, url_prefix='/customers')
    app.register_blueprint(audit_bp)
    app.register_blueprint(sales_invoices_bp)
    app.register_blueprint(purchase_bills_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(journal_entries_bp)
    app.register_blueprint(reports_bp)


    migrate.init_app(app, db)

    # Global error handlers
    from flask import render_template
    from app.errors.utils import log_error_to_db

    @app.errorhandler(404)
    def not_found_error(error):
        app.logger.warning(f"404 error: {request.url}")
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden_error(error):
        from flask_login import current_user
        app.logger.warning(
            f"403 error: {request.url} by user {current_user.id if current_user.is_authenticated else 'anonymous'}"
        )
        return render_template('errors/403.html'), 403

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.critical(f"500 error: {request.url}", exc_info=True)
        log_error_to_db(error, severity='CRITICAL')
        db.session.rollback()
        return render_template('errors/500.html'), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        app.logger.critical(f"Unhandled exception: {request.url}", exc_info=True)
        log_error_to_db(e, severity='CRITICAL')
        db.session.rollback()
        # Return 500 error page
        return render_template('errors/500.html'), 500

    return app
