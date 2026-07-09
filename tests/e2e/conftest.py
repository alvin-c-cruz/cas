"""
Fixtures for the Playwright e2e smoke suite.

`live_server` launches tests/e2e/_serve.py in a subprocess against an isolated temp
SQLite DB (seeded with admin/admin123, COA, VAT/WHT, and vendors V001-V003), polls until
it answers, and yields the base URL. `logged_in_page` logs the admin in through the real
login form (handling the anti-autofill readonly fields).

The `page` fixture comes from pytest-playwright. Requires the chromium browser to be
installed once: `python -m playwright install chromium`.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _free_port():
    s = socket.socket()
    try:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
    finally:
        s.close()


# MODULE scope (not session): the dev server subprocess progressively slows as it
# handles many requests over a long run (a connection/session leak in dev config —
# tracked separately), which made the LATER e2e tests in a big batch time out on the
# post-login sidebar wait. A fresh server per test file keeps each batch small and
# healthy, fixing the flaky pre-push guard without masking the underlying leak.
def _launch_seeded_server(tmp_path_factory, extra_env=None):
    """Start _serve.py against a fresh temp DB and yield its base URL.

    `extra_env` overlays onto the child environment — e.g. E2E_SEED_PROFILE=sales
    to additionally enable the optional Sales-cycle modules and seed products +
    a confirmed Sales Order (used by the Quotation/Delivery-Receipt smokes). The
    default (no profile) keeps the lean AP/SI/CDV/CRV seed so those smokes are
    unaffected by the Sales-cycle module toggles (products ON changes their forms).
    """
    port = _free_port()
    db_path = tmp_path_factory.mktemp('e2e_db') / 'cas_e2e.db'
    log_path = tmp_path_factory.mktemp('e2e_log') / 'server.log'

    env = dict(os.environ)
    env['FLASK_ENV'] = 'development'
    env['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + str(db_path).replace('\\', '/')
    env.setdefault('SECRET_KEY', 'e2e-secret-key-deadbeefdeadbeefdeadbeefdeadbeef')
    env['E2E_PORT'] = str(port)
    env['PYTHONPATH'] = PROJECT_ROOT + os.pathsep + env.get('PYTHONPATH', '')
    if extra_env:
        env.update(extra_env)

    serve = os.path.join(PROJECT_ROOT, 'tests', 'e2e', '_serve.py')
    base = f'http://127.0.0.1:{port}'

    def _log():
        try:
            with open(log_path, encoding='utf-8', errors='replace') as fh:
                return fh.read()
        except OSError:
            return '(no server log)'

    with open(log_path, 'w', encoding='utf-8') as logf:
        proc = subprocess.Popen(
            [sys.executable, serve], env=env, cwd=PROJECT_ROOT,
            stdout=logf, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.time() + 45
            while True:
                if proc.poll() is not None:
                    raise RuntimeError('e2e server exited early:\n' + _log())
                if time.time() > deadline:
                    raise RuntimeError('e2e server did not become ready in time:\n' + _log())
                try:
                    with urllib.request.urlopen(base + '/login', timeout=2) as r:
                        if r.status == 200:
                            break
                except (urllib.error.URLError, ConnectionError, OSError):
                    time.sleep(0.5)
            yield base
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope='module')
def e2e_server(tmp_path_factory):
    yield from _launch_seeded_server(tmp_path_factory)


@pytest.fixture(scope='module')
def sales_e2e_server(tmp_path_factory):
    """Server with the Sales-cycle modules ON + products + a confirmed SO seeded.

    Isolated from `e2e_server` so enabling `products`/`sales_orders`/`quotations`/
    `delivery_receipts` never perturbs the lean AP/SI/CDV/CRV smokes."""
    yield from _launch_seeded_server(tmp_path_factory, {'E2E_SEED_PROFILE': 'sales'})


def _login_admin(page, base):
    """Log the seeded admin in via the real form (password field is readonly until focused)."""
    page.goto(base + '/login')
    page.click('#username')
    page.fill('#username', 'admin')
    page.click('#password')
    page.fill('#password', 'admin123')
    page.click('button[type="submit"]')
    # 1 seeded branch -> auto-selected -> dashboard. Wait for the sidebar to confirm login.
    page.wait_for_selector('text=Accounts Payable', timeout=15000)
    return page


@pytest.fixture
def logged_in_page(page, e2e_server):
    """Admin logged in against the default (lean) seed server."""
    return _login_admin(page, e2e_server)


@pytest.fixture
def logged_in_sales_page(page, sales_e2e_server):
    """Admin logged in against the Sales-cycle seed server (products + confirmed SO)."""
    return _login_admin(page, sales_e2e_server)
