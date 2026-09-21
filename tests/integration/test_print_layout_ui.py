"""The picker as RENDERED. Every absence assertion is scoped to the applied attribute:
the page's inline <style> block names these classes, so a bare `'pp-layout-picker' not
in body` could never fail and would be a test that only looks like one."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.print_layouts.models import PrintLayout
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _mk(name, is_default=False):
    r = PrintLayout(doc_type='purchase_orders', scope_id=1, name=name,
                    is_default=is_default, payload=json.dumps({}))
    db.session.add(r); db.session.commit()
    return r


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders is an optional module (default_enabled=False) -- without this,
    enforce_module_access 404s the route for every role, admin included. Mirrors
    test_po_amend.py's identically-named fixture."""
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    # The preprinted overlay is opt-in per company; the plain print.html carries no
    # picker at all, so every test in this file needs the preprinted form selected.
    AppSettings.set_setting('po_print_form', 'preprinted')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    """Direct-session login, scoped to the PO's branch. Mirrors
    tests/integration/_so_helpers.py::_login and test_po_amend.py's local copy.

    Flask-Login caches the resolved user on flask.g for the life of the app context
    that conftest's db_session/app fixtures keep open for the whole test, so a
    mid-test user switch (admin -> staff) needs the g pop or the second login never
    takes effect."""
    import flask
    flask.g.pop('_login_user', None)
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def vendor_acme(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='V900', name='ACME', is_active=True, default_vat_category='V12DG')
    db.session.add(v)
    db.session.commit()
    return v


@pytest.fixture
def po_fixture(client, db_session, admin_user, main_branch, vendor_acme):
    """An APPROVED PO on main_branch -- a draft PO refuses to print (see
    purchase_orders.views.print_po's po_print_access gate), and main_branch.id == 1
    is what test-file-wide `_mk(...)`'s scope_id=1 is built to match.

    Logs in as admin by default so a test that doesn't care about role can just ask
    for this fixture; the staff-only test below re-logs-in over it."""
    po = PurchaseOrder(po_number='00997', order_date=date(2026, 8, 5), status='approved',
                       vendor_id=vendor_acme.id, vendor_name=vendor_acme.name, notes='',
                       payment_terms='Net 30', vat_treatment='inclusive',
                       branch_id=main_branch.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='widget', quantity=Decimal('10'),
        unit_price=Decimal('5.00'), amount=Decimal('50.00'),
        line_total=Decimal('50.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0')))
    po.calculate_totals()
    db.session.add(po)
    db.session.commit()
    _login(client, admin_user, main_branch)
    return po


def test_the_print_screen_lists_every_layout(client, db_session, main_branch, po_fixture):
    _mk('Default', is_default=True); _mk('Purchasing - HP')
    body = client.get('/purchase-orders/%d/print' % po_fixture.id).data.decode()
    assert 'class="pp-layout-picker"' in body
    assert 'Purchasing - HP' in body


def test_delete_is_absent_from_the_toolbar_for_staff(client, db_session, main_branch,
                                                     po_fixture, staff_user):
    _mk('Default', is_default=True)
    # staff can edit a layout (app/users/models.py:130) but not delete one
    # (app/users/models.py:156) -- grant the module book permission
    # (default-deny for staff) and switch the session onto this user.
    perms = staff_user.get_book_permissions()
    perms['purchase_orders'] = True
    staff_user.set_book_permissions(perms)
    db.session.commit()
    _login(client, staff_user, main_branch)
    body = client.get('/purchase-orders/%d/print' % po_fixture.id).data.decode()
    assert 'id="ppDeleteLayoutBtn"' not in body


def test_the_copy_names_printers_not_people(client, db_session, main_branch, po_fixture):
    """Without this line the library fills with per-person duplicates of one printer."""
    _mk('Default', is_default=True)
    body = client.get('/purchase-orders/%d/print' % po_fixture.id).data.decode()
    assert 'Name it after the printer, not the person' in body
