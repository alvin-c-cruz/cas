"""Shared test helpers for Sales Order integration tests.

Leading underscore keeps pytest from collecting this module as a test module.
Moved verbatim out of test_sales_orders_crud.py (Task 4) so test_so_amendment.py
can reuse them without duplication.
"""
import pytest
from decimal import Decimal


@pytest.fixture(autouse=True)
def sales_orders_module_enabled(db_session):
    """Enable the optional sales_orders module for all SO tests.

    Also enables job_order_slips: print_job_order's endpoint prefix is registered
    under the job_order_slips module key (Task 5), not sales_orders, so the
    company-level module_enabled() gate -- which applies to every role including
    admin -- would otherwise 404 this file's print_job_order tests.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    AppSettings.set_setting('module_enabled:job_order_slips', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


# ── helpers ──────────────────────────────────────────────────────────────────

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    # Flask-Login caches the loaded user on flask.g for the life of the app
    # context. The `app` fixture keeps ONE app context open for the whole test
    # function, and Flask's test client reuses that same context per request
    # rather than pushing a fresh one -- so g._login_user (and therefore
    # current_user) would otherwise stay stale across a mid-test user switch
    # (log in as accountant, do something, log in as staff: current_user would
    # still resolve to accountant on the next request). Bust the cache here so
    # every _login() call is guaranteed to take effect on the very next request.
    import flask
    flask.g.pop('_login_user', None)


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _customer(db_session):
    from app.customers.models import Customer
    c = Customer(code='ACME01', name='Acme', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _product(db_session, code='WIDGET', name='Widget'):
    from app.units_of_measure.models import UnitOfMeasure
    from app.products.models import Product
    uom = UnitOfMeasure.query.filter_by(code='pcs').first()
    if uom is None:
        uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
        db_session.add(uom); db_session.commit()
    p = Product(code=code, name=name, default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('100.00'), is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _enable_products(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    AppSettings.set_setting('module_enabled:products', '1')
    db_session.commit()
    clear_module_config_cache()
