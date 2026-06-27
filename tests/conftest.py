"""
Pytest configuration and fixtures for CAS application testing
"""
import pytest
import os
from app import create_app, db
from app.users.models import User
from app.branches.models import Branch
from app.accounts.models import Account
from werkzeug.security import generate_password_hash


@pytest.fixture(scope='session')
def app():
    """Create application for testing session"""
    # Set testing environment variables
    os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only'
    os.environ['TESTING'] = 'True'

    # Create app with testing config
    app = create_app('testing')

    # Establish application context
    with app.app_context():
        yield app


@pytest.fixture(scope='function')
def db_session(app):
    """Create a new database session for each test"""
    with app.app_context():
        # Create all tables
        db.create_all()

        # Yield the session
        yield db.session

        # Cleanup after test
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app, db_session):
    """Test client for making requests"""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI test runner"""
    return app.test_cli_runner()


@pytest.fixture
def auth_headers():
    """Helper for creating authorization headers"""
    def _headers(token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers
    return _headers


# User Fixtures

@pytest.fixture
def admin_user(db_session):
    """Create an admin user"""
    user = User(
        username='admin',
        email='admin@test.com',
        full_name='Admin User',
        role='admin',
        is_active=True
    )
    user.set_password('admin123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def accountant_user(db_session, main_branch):
    """Create an accountant user assigned to main_branch.

    Accountants are now branch-scoped (like staff/viewer) — they must have at least
    one assigned branch or the before_request gate will redirect them to the picker
    with no options.  Assigning main_branch here keeps every existing test green
    without changes; tests that need an unassigned accountant create one directly.
    """
    user = User(
        username='accountant',
        email='accountant@test.com',
        full_name='Accountant User',
        role='accountant',
        is_active=True
    )
    user.set_password('accountant123')
    from app.users.module_access import default_all_permissions
    user.set_book_permissions(default_all_permissions())
    db_session.add(user)
    db_session.flush()  # get user.id before set_branches
    user.set_branches([main_branch])
    db_session.commit()
    return user


@pytest.fixture
def staff_user(db_session):
    """Create a staff user with all transaction books granted.

    Per-module access (book_permissions) is now enforced for staff, so a default-deny
    staff user would be blocked from the transaction modules. Grant them all here so
    existing tests that exercise AP/SI/CD as staff keep working; tests that specifically
    exercise the gating set their own book_permissions.
    """
    user = User(
        username='staff',
        email='staff@test.com',
        full_name='Staff User',
        role='staff',
        is_active=True
    )
    user.set_password('staff123')
    user.set_book_permissions({
        'accounts_receivable': True,
        'collections': True,
        'accounts_payable': True,
        'payments': True,
        'journal_entries': True,
        # Phase 2 master/ledger modules (deny-by-default in prod; granted here for tests)
        'customers': True,
        'vendors': True,
        'chart_of_accounts': True,
        'ap_aging': True,
        'ar_aging': True,
    })
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def viewer_user(db_session):
    """Create a viewer user"""
    user = User(
        username='viewer',
        email='viewer@test.com',
        full_name='Viewer User',
        role='viewer',
        is_active=True
    )
    user.set_password('viewer123')
    from app.users.module_access import default_all_permissions
    user.set_book_permissions(default_all_permissions())
    db_session.add(user)
    db_session.commit()
    return user


# Branch Fixtures

@pytest.fixture
def main_branch(db_session):
    """Create main branch"""
    branch = Branch(
        code='MAIN',
        name='Main Office',
        address='123 Main St',
        phone='123-456-7890',
        email='main@test.com',
        is_active=True
    )
    db_session.add(branch)
    db_session.commit()
    return branch


@pytest.fixture
def branch_manila(db_session):
    """Create Manila branch"""
    branch = Branch(
        code='MNL',
        name='Manila Branch',
        address='456 Manila St',
        phone='987-654-3210',
        email='manila@test.com',
        is_active=True
    )
    db_session.add(branch)
    db_session.commit()
    return branch


# Account Fixtures

@pytest.fixture
def cash_account(db_session):
    """Create a cash account"""
    account = Account(
        code='1001',
        name='Cash on Hand',
        account_type='Asset',
        classification='Current Asset',
        normal_balance='Debit',
        description='Petty cash and cash on hand'
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture
def revenue_account(db_session):
    """Create a revenue account"""
    account = Account(
        code='4001',
        name='Sales Revenue',
        account_type='Income',
        classification='Operating Revenue',
        normal_balance='Credit',
        description='Revenue from sales'
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture
def expense_account(db_session):
    """Create an expense account"""
    account = Account(
        code='5001',
        name='Office Supplies',
        account_type='Expense',
        classification='Operating Expense',
        normal_balance='Debit',
        description='Office supplies expense'
    )
    db_session.add(account)
    db_session.commit()
    return account


# Authentication Helpers

@pytest.fixture
def authenticated_client(client, admin_user):
    """Client authenticated as admin"""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def login_user():
    """Helper function to login a user in test client"""
    def _login(client, username, password):
        return client.post('/login', data={
            'username': username,
            'password': password
        }, follow_redirects=True)
    return _login


@pytest.fixture
def logout_user():
    """Helper function to logout current user"""
    def _logout(client):
        return client.get('/logout', follow_redirects=True)
    return _logout


# Request Context Helper

@pytest.fixture
def app_context(app):
    """Application context for tests"""
    with app.app_context():
        yield


# Database Helper

@pytest.fixture
def db_with_data(db_session, admin_user, main_branch, cash_account, revenue_account):
    """Database with common test data"""
    return {
        'admin': admin_user,
        'branch': main_branch,
        'cash': cash_account,
        'revenue': revenue_account
    }
