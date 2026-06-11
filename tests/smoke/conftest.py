import os
import socket
import tempfile
import threading
import time

import pytest

from app import create_app, db as _db
from app.users.models import User
from app.branches.models import Branch
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.vat_categories.models import VATCategory


@pytest.fixture(scope="session")
def smoke_app():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)

    os.environ.setdefault('SECRET_KEY', 'smoke-test-secret-key-123')
    app = create_app('testing')
    app.config['TESTING'] = False
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'check_same_thread': False}}

    with app.app_context():
        _db.create_all()
        _seed_smoke_data(app)
        yield app
        _db.drop_all()

    os.unlink(db_path)


def _seed_smoke_data(app):
    with app.app_context():
        branch = Branch(name='Main Branch', code='MAIN', is_active=True)
        _db.session.add(branch)
        _db.session.flush()

        user = User(
            username='smokeuser',
            email='smoke@example.com',
            full_name='Smoke Tester',
            role='accountant',
            is_active=True,
        )
        user.set_password('Smoke123!')
        _db.session.add(user)

        vat = VATCategory(code='VAT', name='VATable (12%)', rate=12.0, is_active=True)
        _db.session.add(vat)

        acct = Account(
            code='50101',
            name='Purchases',
            account_type='Expense',
            normal_balance='Debit',
            is_active=True,
        )
        _db.session.add(acct)

        vendor = Vendor(
            name='Test Supplier',
            code='SUP001',
            default_vat_category='VAT',
            payment_terms='Net 30',
            is_active=True,
        )
        _db.session.add(vendor)

        _db.session.commit()


@pytest.fixture(scope="session")
def live_url(smoke_app):
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()

    t = threading.Thread(
        target=lambda: smoke_app.run(host='127.0.0.1', port=port, use_reloader=False, threaded=True),
        daemon=True,
    )
    t.start()
    time.sleep(1.5)
    return f'http://127.0.0.1:{port}'


@pytest.fixture
def logged_in_page(page, live_url):
    page.goto(f'{live_url}/login')
    # Both fields start readonly; focusing removes readonly (per login page JS).
    # Use evaluate to strip readonly first, then fill.
    page.evaluate("document.getElementById('username').removeAttribute('readonly')")
    page.fill('#username', 'smokeuser')
    page.evaluate("document.getElementById('password').removeAttribute('readonly')")
    page.fill('#password', 'Smoke123!')
    page.click('button[type="submit"]')
    page.wait_for_url(f'{live_url}/**', timeout=10000)
    return page, live_url
