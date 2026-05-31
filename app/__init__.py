from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def create_app(config=None):
    """Application factory pattern"""
    app = Flask(__name__)

    # Default configuration
    app.config['SECRET_KEY'] = config.get('SECRET_KEY', 'your-secret-key-here') if config else 'your-secret-key-here'
    app.config['SQLALCHEMY_DATABASE_URI'] = config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///cas.db') if config else 'sqlite:///cas.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions
    db.init_app(app)

    # Register blueprints
    from app.dashboard.views import dashboard_bp
    from app.accounts.views import accounts_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp, url_prefix='/accounts')

    # Create database tables
    with app.app_context():
        db.create_all()

        # Add sample accounts if database is empty
        from app.accounts.models import Account
        if Account.query.count() == 0:
            sample_accounts = [
                Account(code='1000', name='Cash', account_type='Asset', classification='Current', normal_balance='Debit'),
                Account(code='1100', name='Accounts Receivable', account_type='Asset', classification='Current', normal_balance='Debit'),
                Account(code='1200', name='Inventory', account_type='Asset', classification='Current', normal_balance='Debit'),
                Account(code='1500', name='Equipment', account_type='Asset', classification='Non-Current', normal_balance='Debit'),
                Account(code='2000', name='Accounts Payable', account_type='Liability', classification='Current', normal_balance='Credit'),
                Account(code='2100', name='Notes Payable', account_type='Liability', classification='Non-Current', normal_balance='Credit'),
                Account(code='3000', name='Common Stock', account_type='Equity', classification='', normal_balance='Credit'),
                Account(code='3100', name='Retained Earnings', account_type='Equity', classification='', normal_balance='Credit'),
                Account(code='4000', name='Sales Revenue', account_type='Revenue', classification='', normal_balance='Credit'),
                Account(code='5000', name='Cost of Goods Sold', account_type='Expense', classification='', normal_balance='Debit'),
                Account(code='5100', name='Salaries Expense', account_type='Expense', classification='', normal_balance='Debit'),
                Account(code='5200', name='Rent Expense', account_type='Expense', classification='', normal_balance='Debit'),
            ]
            db.session.add_all(sample_accounts)
            db.session.commit()
            print("Sample accounts added to database")

    return app
