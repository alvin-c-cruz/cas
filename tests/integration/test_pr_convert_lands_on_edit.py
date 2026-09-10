"""Converting a requisition lands the buyer on the ORDER'S EDIT PAGE.

Owner, 2026-09-10: clicking CONVERT should go to /purchase-orders/<id>/edit
"so user can proceed to edit at once", with the vendor field focused.

It used to land on the order's VIEW page, which is a dead end for the one thing
that always has to happen next: the converted order carries NO VENDOR. The
requisition does not name one (it asks for goods, it does not choose a supplier),
and purchase_requests.convert() builds the PurchaseOrder without a vendor_id --
so the buyer had to read the view page, find Edit, and click again before they
could do anything at all.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture
def approved_pr(db_session, main_branch, admin_user):
    pr = PurchaseRequest(pr_number='CONV-1', request_date=date(2026, 9, 10),
                         date_needed=date(2026, 9, 30), reason='Stock',
                         status='approved', branch_id=main_branch.id,
                         created_by_id=admin_user.id)
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='Cement', quantity=Decimal('10')))
    db.session.add(pr); db.session.commit()
    return pr


def _login(client, admin_user, main_branch, login_user):
    # purchase_requests depends on purchase_orders and both default to OFF in
    # tests; without this, convert() is refused by the module gate and every
    # assertion below fails for a reason unrelated to what it is testing.
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('purchase_orders', 'purchase_requests'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    db.session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id


class TestWhereConvertLands:

    def test_it_redirects_to_the_orders_EDIT_page(self, client, db_session,
                                                  main_branch, admin_user,
                                                  approved_pr, login_user):
        _login(client, admin_user, main_branch, login_user)
        resp = client.post('/purchase-requests/%s/convert' % approved_pr.id)
        assert resp.status_code in (301, 302), resp.status_code
        po = PurchaseOrder.query.filter_by(purchase_request_id=approved_pr.id).one()
        assert resp.headers['Location'].endswith('/purchase-orders/%s/edit' % po.id), (
            resp.headers['Location'])

    def test_the_converted_order_really_has_no_vendor_yet(
            self, client, db_session, main_branch, admin_user, approved_pr,
            login_user):
        """The reason edit is the right destination. If this ever stops being
        true, the redirect above is worth revisiting rather than assumed."""
        _login(client, admin_user, main_branch, login_user)
        client.post('/purchase-requests/%s/convert' % approved_pr.id)
        po = PurchaseOrder.query.filter_by(purchase_request_id=approved_pr.id).one()
        assert po.vendor_id is None

    def test_the_edit_page_focuses_the_vendor_when_it_is_empty(
            self, client, db_session, main_branch, admin_user, approved_pr,
            login_user):
        _login(client, admin_user, main_branch, login_user)
        client.post('/purchase-requests/%s/convert' % approved_pr.id)
        po = PurchaseOrder.query.filter_by(purchase_request_id=approved_pr.id).one()
        html = client.get('/purchase-orders/%s/edit' % po.id).data.decode()
        # Control: the vendor picker rendered at all.
        assert 'id="vendorSelect"' in html
        assert 'focusVendorOnLoad = true' in html, (
            'the converted order has no vendor, so the buyer should land in that '
            'field rather than hunting for it')

    def test_an_order_that_already_has_a_vendor_is_not_hijacked(
            self, client, db_session, main_branch, admin_user, approved_pr,
            login_user):
        """Editing an ordinary order must not steal focus: the buyer may be
        going straight to a line item, and a stolen focus scrolls the page."""
        _login(client, admin_user, main_branch, login_user)
        client.post('/purchase-requests/%s/convert' % approved_pr.id)
        po = PurchaseOrder.query.filter_by(purchase_request_id=approved_pr.id).one()
        from app.vendors.models import Vendor
        v = Vendor(code='CONV-V', name='Converted Vendor')
        db.session.add(v); db.session.commit()
        po.vendor_id = v.id
        po.vendor_name = v.name
        db.session.commit()
        html = client.get('/purchase-orders/%s/edit' % po.id).data.decode()
        assert 'focusVendorOnLoad = true' not in html
