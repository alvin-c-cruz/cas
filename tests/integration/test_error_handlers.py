"""Global error handlers — active in production (DEBUG off), disabled in development.

The generic 404/403/500/Exception handlers in create_app register only when
``app.debug`` is False, so production gets friendly error pages + DB error logging
while development keeps raw tracebacks. These tests pin both sides of that contract.

The 'testing_errors' config (DEBUG/TESTING off, propagation off) lets the test client
route errors through the handlers the way production would; plain 'testing' (DEBUG on)
is used to prove the handlers stay off in development.
"""
import os

import pytest

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')

from app import create_app, db
from app.errors.models import ErrorLog


def _app_with_boom(config_name):
    """Build an app on the given config with a route that raises, for 500 testing."""
    app = create_app(config_name)

    def boom():
        raise RuntimeError('kaboom for tests')

    app.add_url_rule('/__boom__', '__boom__', boom)

    # A POST-only route, so a GET raises Werkzeug's MethodNotAllowed (405). Used
    # to prove the catch-all Exception handler does not downgrade an HTTP status
    # to 500 (the /attachments/.../upload route is POST-only and did exactly that
    # on a GET before the fix).
    def post_only():
        return 'ok'

    app.add_url_rule('/__postonly__', '__postonly__', post_only, methods=['POST'])
    return app


@pytest.fixture
def prod_app():
    """Production-like app: DEBUG off, handlers active."""
    app = _app_with_boom('testing_errors')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def dev_app():
    """Development-like app: DEBUG on, handlers disabled."""
    app = _app_with_boom('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


class TestErrorHandlersActiveInProduction:
    def test_unknown_url_renders_friendly_404(self, prod_app):
        resp = prod_app.test_client().get('/no-such-page')
        assert resp.status_code == 404
        body = resp.get_data(as_text=True)
        assert "doesn't exist or has been moved" in body  # from errors/404.html

    def test_unhandled_exception_renders_friendly_500(self, prod_app):
        resp = prod_app.test_client().get('/__boom__')
        assert resp.status_code == 500
        body = resp.get_data(as_text=True)
        assert "Something went wrong on our end" in body  # from errors/500.html

    def test_unhandled_exception_is_logged_to_db(self, prod_app):
        prod_app.test_client().get('/__boom__')
        logged = ErrorLog.query.filter_by(error_type='RuntimeError').all()
        assert len(logged) == 1
        assert logged[0].severity == 'CRITICAL'
        assert 'kaboom for tests' in logged[0].error_message

    def test_wrong_method_keeps_405_not_downgraded_to_500(self, prod_app):
        """A GET on a POST-only route is a 405, not a server error. The catch-all
        Exception handler must not relabel HTTP errors as 500 (regression:
        /attachments/.../upload returned a 500 page on a GET)."""
        resp = prod_app.test_client().get('/__postonly__')
        assert resp.status_code == 405
        assert 'Something went wrong on our end' not in resp.get_data(as_text=True)

    def test_http_error_is_not_logged_as_a_crash(self, prod_app):
        """A routine 405 is client error, not an app crash — it must not fill the
        error log with CRITICAL rows the way a real 500 does."""
        prod_app.test_client().get('/__postonly__')
        assert ErrorLog.query.filter_by(error_type='MethodNotAllowed').count() == 0


class TestErrorHandlersDisabledInDevelopment:
    def test_unhandled_exception_propagates_raw(self, dev_app):
        # No friendly page in dev — the raw traceback surfaces (exception propagates).
        with pytest.raises(RuntimeError, match='kaboom for tests'):
            dev_app.test_client().get('/__boom__')

    def test_unknown_url_does_not_render_friendly_page(self, dev_app):
        resp = dev_app.test_client().get('/no-such-page')
        assert resp.status_code == 404
        assert "doesn't exist or has been moved" not in resp.get_data(as_text=True)
