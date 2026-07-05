"""
Application factory for CAS — a general-purpose, BIR-compliant
computerized accounting system for Philippine SMEs. Industry-agnostic
and used by multiple companies across different industries: trading,
services, retail, construction, and any other line of business that
needs double-entry books.
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
cache = Cache()
# IP-based rate limiter. No default limits — applied opt-in per route
# (e.g. auth endpoints) via @limiter.limit(...). Storage/enabled come from config.
limiter = Limiter(key_func=get_remote_address, default_limits=[])

def create_app(config_name=None):
    """Application factory pattern with secure configuration"""
    app = Flask(__name__)

    # Load configuration from config.py
    from config import get_config
    config_obj = get_config(config_name)
    app.config.from_object(config_obj)

    # Configure logging
    if not app.debug and not app.testing:
        log_fmt = logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        )
        try:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')
            os.makedirs(log_dir, exist_ok=True)

            file_handler = RotatingFileHandler(
                os.path.join(log_dir, 'cas_app.log'),
                maxBytes=10485760,
                backupCount=10
            )
            file_handler.setFormatter(log_fmt)
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)

            error_handler = RotatingFileHandler(
                os.path.join(log_dir, 'cas_errors.log'),
                maxBytes=10485760,
                backupCount=10
            )
            error_handler.setFormatter(log_fmt)
            error_handler.setLevel(logging.ERROR)
            app.logger.addHandler(error_handler)
        except (OSError, PermissionError):
            # Log directory not writable (e.g. read-only FS on PythonAnywhere);
            # fall back to stderr — the platform captures it in its own error log.
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(log_fmt)
            stream_handler.setLevel(logging.INFO)
            app.logger.addHandler(stream_handler)

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
        from flask import session
        from flask_login import current_user
        count = 0
        if current_user.is_authenticated:
            from app.dashboard.action_items_service import count_action_items
            count = count_action_items(current_user, session.get('selected_branch_id'))
        return {'action_items_count': count}

    # Make current branch available in all templates
    @app.context_processor
    def inject_current_branch():
        from flask_login import current_user
        from flask import session
        current_branch = None
        multi_branch = False
        accessible_branches = []
        if current_user.is_authenticated:
            branch_id = session.get('selected_branch_id')
            if branch_id:
                from app.branches.models import Branch
                current_branch = db.session.get(Branch, branch_id)
            # Hide branch indicators/labels entirely when the company has a
            # single active branch (nothing to disambiguate).
            try:
                from app.branches.models import Branch
                multi_branch = Branch.query.filter_by(is_active=True).count() > 1
            except Exception:
                multi_branch = False
            # Branches this user may switch to (drives the sidebar quick-switcher).
            try:
                from app.users.utils import get_accessible_branches
                accessible_branches = get_accessible_branches(current_user)
            except Exception:
                accessible_branches = []
        return {'current_branch': current_branch, 'multi_branch': multi_branch,
                'accessible_branches': accessible_branches}

    # Make company name and logo available in all templates (sidebar brand)
    @app.context_processor
    def inject_company_info():
        try:
            from app.settings import AppSettings
            company_name = AppSettings.get_setting('company_name') or 'Company Name'
            company_logo = AppSettings.get_setting('company_logo') or None
        except Exception:
            company_name = 'Company Name'
            company_logo = None
        return {'company_name': company_name, 'company_logo': company_logo}

    # Per-user module access helpers for templates (sidebar gating + the user-edit form)
    from app.users.module_access import (can_access_module, visible_transactions,
                                          visible_modules, MODULE_REGISTRY, module_enabled,
                                          build_sidebar)
    app.jinja_env.globals['can_access_module'] = can_access_module
    app.jinja_env.globals['visible_transactions'] = visible_transactions
    app.jinja_env.globals['visible_modules'] = visible_modules
    app.jinja_env.globals['module_registry'] = MODULE_REGISTRY
    app.jinja_env.globals['module_enabled'] = module_enabled
    app.jinja_env.globals['build_sidebar'] = build_sidebar

    # Add custom Jinja2 filter for JSON parsing
    @app.template_filter('from_json')
    def from_json_filter(s):
        import json
        try:
            return json.loads(s) if s else {}
        except:
            return {}

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Ensure upload directories exist at startup
    import os as _os
    _os.makedirs(_os.path.join(app.config['UPLOAD_FOLDER'], 'accounts_payable'), exist_ok=True)
    _os.makedirs(_os.path.join(app.config['UPLOAD_FOLDER'], 'company'), exist_ok=True)

    # Initialize caching
    cache.init_app(app, config={
        'CACHE_TYPE': 'SimpleCache',  # In-memory cache
        'CACHE_DEFAULT_TIMEOUT': 3600  # 1 hour default timeout
    })

    login_manager.init_app(app)
    login_manager.login_view = 'users.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from app.users.models import User
        return db.session.get(User, int(user_id))

    # Import models for migrations (must be before migrate.init_app)
    from app.accounts.models import Account
    from app.accounts.approval_models import AccountChangeRequest
    from app.users.models import User
    from app.users.approved_emails import ApprovedEmail
    from app.branches.models import Branch
    from app.vendors.models import Vendor
    from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
    from app.sales_vat_categories.models import SalesVATCategory, SalesVATCategoryChangeRequest
    from app.withholding_tax.models import WithholdingTax, WithholdingTaxChangeRequest
    from app.customers.models import Customer
    from app.audit.models import AuditLog
    from app.notifications.models import Notification
    from app.settings import AppSettings
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem, SalesInvoiceAttachment
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem, AccountsPayableAttachment
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine, CDVExpenseLine
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine, CRVRevenueLine
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.errors.models import ErrorLog
    from app.periods.models import AccountingPeriod
    from app.year_end.models import FiscalYearClose
    from app.units_of_measure.models import UnitOfMeasure
    from app.products.models import Product
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    from app.backup.models import BackupRun

    # Register blueprints
    from app.dashboard.views import dashboard_bp
    from app.accounts.views import accounts_bp
    from app.users.views import users_bp
    from app.api.views import api_bp
    from app.branches.views import branches_bp
    from app.vendors.views import vendors_bp
    from app.vat_categories.views import vat_categories_bp
    from app.sales_vat_categories.views import sales_vat_categories_bp
    from app.withholding_tax.views import withholding_tax_bp
    from app.customers.views import customers_bp
    from app.audit.views import audit_bp
    from app.sales_invoices.views import sales_invoices_bp
    from app.accounts_payable.views import accounts_payable_bp
    from app.journal_entries.views import journal_entries_bp
    from app.journals.views import journals_bp
    from app.reports.views import reports_bp
    from app.errors.views import errors_bp
    from app.periods.views import periods_bp
    from app.company_settings.views import company_settings_bp
    from app.cash_disbursements.views import cash_disbursements_bp
    from app.cash_receipts.views import cash_receipts_bp
    from app.year_end.views import year_end_bp
    from app.staff_management.views import staff_management_bp
    from app.units_of_measure.views import units_of_measure_bp
    from app.products.views import products_bp
    from app.sales_orders.views import sales_orders_bp
    from app.opening_balances.views import opening_balances_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp, url_prefix='/accounts')
    app.register_blueprint(users_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(branches_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(vat_categories_bp, url_prefix='/vat-categories')
    app.register_blueprint(sales_vat_categories_bp, url_prefix='/sales-vat-categories')
    app.register_blueprint(withholding_tax_bp, url_prefix='/withholding-tax')
    app.register_blueprint(customers_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(sales_invoices_bp)
    app.register_blueprint(accounts_payable_bp)
    app.register_blueprint(journal_entries_bp)
    app.register_blueprint(journals_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(errors_bp)
    app.register_blueprint(periods_bp)
    app.register_blueprint(company_settings_bp, url_prefix='/settings')
    app.register_blueprint(cash_disbursements_bp)
    app.register_blueprint(cash_receipts_bp)
    app.register_blueprint(year_end_bp)
    app.register_blueprint(staff_management_bp)
    app.register_blueprint(units_of_measure_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(sales_orders_bp)
    app.register_blueprint(opening_balances_bp)

    from app.backup.views import backup_bp
    app.register_blueprint(backup_bp)
    from app.backup.cli import (backup_run_cmd, backup_verify_cmd, backup_restore_cmd,
                                backup_mint_token_cmd)
    app.cli.add_command(backup_run_cmd)
    app.cli.add_command(backup_verify_cmd)
    app.cli.add_command(backup_restore_cmd)
    app.cli.add_command(backup_mint_token_cmd)

    migrate.init_app(app, db)

    # Serve favicon at the root so the browser's automatic /favicon.ico
    # request doesn't 404 on every page.
    @app.route('/favicon.ico')
    def favicon():
        from flask import send_from_directory
        return send_from_directory(
            app.static_folder, 'favicon.svg', mimetype='image/svg+xml'
        )

    # Register CLI commands
    @app.cli.command('seed-db')
    def seed_database():
        """Seed database with initial data (admin, branch, chart of accounts, etc.)"""
        from app.seeds.seed_data import seed_all

        print("\n" + "="*60)
        print("DATABASE SEEDING")
        print("="*60)

        results = seed_all(force=False)

        print("\n" + "="*60)
        print("SEEDING SUMMARY")
        print("="*60)
        print(f"Admin User: {'Created' if results['admin_user'] else 'Already exists'}")
        print(f"Main Branch: {'Created' if results['main_branch'] else 'Already exists'}")
        print(f"Chart of Accounts: {'Created' if results['chart_of_accounts'] else 'Already exists'}")
        print(f"VAT Categories: {'Created' if results['vat_categories'] else 'Already exists'}")
        print(f"Withholding Tax Codes: {'Created' if results['withholding_tax_codes'] else 'Already exists'}")
        print(f"App Settings: {'Created' if results['app_settings'] else 'Already exists'}")
        print("="*60)
        print("\nDatabase seeding complete!")
        print("\nYou can now:")
        print("  1. Start the application: python flask_app.py")
        print("  2. Login with username: admin")
        print("  3. Password: admin123")
        print("="*60 + "\n")

    @app.cli.command('seed-minimal')
    def seed_minimal_database():
        """Seed database with bare-minimum data for demo/testing (admin, branch, 6 accounts, 4 VAT cats, 3 WHT codes)."""
        from app.seeds.seed_data import seed_minimal
        seed_minimal()

    @app.cli.command('seed-history')
    def seed_history_command():
        """Reset the DB and seed 2021->present APV + CDV demo history."""
        from app.seeds.history_seed import run_seed_history
        summary = run_seed_history(reset=True)
        print("\n[OK] Historical seed complete:")
        for k in ('apv', 'cdv', 'paid', 'partially_paid', 'outstanding',
                  'draft', 'voided', 'unbalanced'):
            print(f"  {k:>15}: {summary[k]}")
        if summary['unbalanced']:
            print("  [WARN] Some posted JEs are unbalanced — investigate before demo.")

    @app.cli.command('seed-demo')
    def seed_demo_command():
        """Build the Zhiyuan Construction demo dataset into the active DB."""
        from app.seeds.demo_seed import run_seed_demo
        summary = run_seed_demo(reset=False)
        print("\n[OK] Demo seed complete:")
        for k in ('si', 'ap', 'crv', 'cdv', 'jv', 'unbalanced'):
            print(f"  {k:>12}: {summary[k]}")
        if summary['unbalanced']:
            print("  [WARN] Some posted JEs are unbalanced — investigate before demo.")

    @app.cli.command('seed-food-demo')
    def seed_food_demo_command():
        """Build the SavorPack Food Manufacturing demo dataset into the active DB."""
        from app.seeds.food_demo import run_seed_food_demo
        summary = run_seed_food_demo(reset=False)
        print("\n[OK] Food demo seed complete:")
        for k in ('si', 'ap', 'crv', 'cdv', 'jv', 'unbalanced'):
            print(f"  {k:>12}: {summary[k]}")
        if summary['unbalanced']:
            print("  [WARN] Some posted JEs are unbalanced — investigate before demo.")

    # Request/Response logging middleware
    @app.before_request
    def log_request_info():
        """Log incoming requests for audit and debugging."""
        from flask_login import current_user
        from flask import request
        app.logger.info(
            f"{request.method} {request.path}",
            extra={
                'user': current_user.username if current_user.is_authenticated else 'anonymous',
                'ip': request.remote_addr,
                'endpoint': request.endpoint
            }
        )

    @app.after_request
    def log_response_info(response):
        """Log response status for failed requests."""
        from flask import request
        from flask_login import current_user
        if response.status_code >= 400:
            app.logger.warning(
                f"{request.method} {request.path} -> {response.status_code}",
                extra={
                    'user': current_user.username if current_user.is_authenticated else 'anonymous',
                    'ip': request.remote_addr
                }
            )
        return response

    @app.before_request
    def enforce_https():
        """Enforce HTTPS in production environments."""
        from flask import request, redirect, url_for

        # Only enforce HTTPS in production
        if app.config.get('ENV') == 'production' or app.config.get('ENFORCE_HTTPS'):
            # Check if request is not secure (not HTTPS)
            if not request.is_secure and not request.headers.get('X-Forwarded-Proto') == 'https':
                # Redirect HTTP to HTTPS
                url = request.url.replace('http://', 'https://', 1)
                return redirect(url, code=301)

    BRANCH_EXEMPT_ENDPOINTS = {
        'users.login',
        'users.logout',
        'users.register',
        'users.select_branch',
        'static',
    }

    @app.before_request
    def validate_branch_session():
        """Ensure session branch_id is valid on every request; auto-select or redirect if not."""
        from flask import session, redirect, url_for, request
        from flask_login import current_user
        from app.users.utils import get_accessible_branches

        if request.endpoint is None or request.endpoint in BRANCH_EXEMPT_ENDPOINTS:
            return
        if not current_user.is_authenticated:
            return

        branch_id = session.get('selected_branch_id')
        accessible = get_accessible_branches(current_user)

        if branch_id is not None:
            if any(b.id == branch_id for b in accessible):
                return  # valid — continue

            # stale or deactivated — clear it and fall through to auto-select logic
            session.pop('selected_branch_id', None)

        # branch_id missing — auto-select if only one accessible branch
        if len(accessible) == 1:
            session['selected_branch_id'] = accessible[0].id
            return

        return redirect(url_for('users.select_branch', next=request.url))

    @app.before_request
    def enforce_module_access():
        """Block non-admin users from modules they have not been granted (book_permissions). Admin is never gated here.

        Optional modules disabled at the instance level return 404 for ALL roles (including
        admin) so that the route appears to not exist for this deployment package."""
        from flask import redirect, url_for, request, flash, abort
        from flask_login import current_user
        from app.users.module_access import module_key_for_endpoint, can_access_module, module_enabled

        if request.endpoint is None or not current_user.is_authenticated:
            return
        key = module_key_for_endpoint(request.endpoint)
        if key:
            if not module_enabled(key):
                abort(404)   # module not part of this instance's package
            if not can_access_module(current_user, key):
                flash('You do not have access to this module.', 'error')
                return redirect(url_for('dashboard.index'))

    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses"""
        # Prevent clickjacking attacks
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'

        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'

        # Enable XSS protection (for older browsers)
        response.headers['X-XSS-Protection'] = '1; mode=block'

        # Referrer policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # HTTP Strict Transport Security (HSTS)
        # Force HTTPS for 1 year (31536000 seconds)
        # includeSubDomains: Apply to all subdomains
        # preload: Allow browser HSTS preload list inclusion
        if app.config.get('ENV') == 'production' or app.config.get('ENFORCE_HTTPS'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'

        # Content Security Policy (basic - adjust as needed)
        # Allow scripts and styles from self and inline (needed for Flask templates)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "frame-ancestors 'self'"
        )
        response.headers['Content-Security-Policy'] = csp

        # Permissions Policy (formerly Feature-Policy)
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

        return response

    # 429 (rate limit) handler — friendly page + audit trail. This is a specific,
    # benign handler and is intentionally kept while the generic error handlers
    # below remain disabled for traceback visibility.
    @app.errorhandler(429)
    def ratelimit_handler(e):
        from flask import render_template, request, flash
        from app.users.forms import LoginForm
        try:
            from app.audit.utils import log_audit
            log_audit(module='auth', action='rate_limited', record_id=None,
                      record_identifier=request.remote_addr,
                      notes=f'Rate limit exceeded on {request.path}: '
                            f'{getattr(e, "description", "")}')
        except Exception:
            pass
        flash('Too many attempts from your network. Please wait a minute and try again.', 'error')
        return render_template('users/login.html', form=LoginForm()), 429

    # Generic error handlers — friendly pages + DB error logging. Registered
    # only when DEBUG is off (production) so development and tests keep raw
    # tracebacks / exception propagation for visibility. The 429 handler above
    # stays active in all environments.
    if not app.debug:
        from flask import render_template, request
        from flask_login import current_user

        @app.errorhandler(404)
        def not_found_error(error):
            app.logger.warning(f"404 error: {request.url}")
            return render_template('errors/404.html'), 404

        @app.errorhandler(403)
        def forbidden_error(error):
            app.logger.warning(
                f"403 error: {request.url} by user "
                f"{current_user.id if current_user.is_authenticated else 'anonymous'}"
            )
            return render_template('errors/403.html'), 403

        @app.errorhandler(500)
        def internal_error(error):
            app.logger.critical(f"500 error: {request.url}", exc_info=True)
            from app.errors.utils import log_error_to_db
            log_error_to_db(error, severity='CRITICAL')
            db.session.rollback()
            return render_template('errors/500.html'), 500

        @app.errorhandler(Exception)
        def unhandled_exception(error):
            app.logger.critical(f"Unhandled exception: {request.url}", exc_info=True)
            from app.errors.utils import log_error_to_db
            log_error_to_db(error, severity='CRITICAL')
            db.session.rollback()
            return render_template('errors/500.html'), 500

    return app
