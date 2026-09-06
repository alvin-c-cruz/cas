"""A Purchase Order is NOT blocked by an unapproved source requisition.

REVERSED 2026-09-06 at the owner's request. From 2026-08-26 an order whose lines
came from a still-submitted (or later rejected/cancelled) requisition was refused
at approve(), and the detail page carried an alert-warning banner explaining why
before the click. Both are gone: pulling a submitted requisition is the ordinary
path, so refusing the order it produced contradicted the workflow the change was
made to serve.

What was given up is recorded in approve()'s own comment -- the order's demand
may never have been authorised, and nothing unwinds the order's lines if the
requisition is later rejected or cancelled. Approving is now the buyer's
judgement.

These tests are the guard that the block stays gone. `unapproved_source_prs()`
itself is deliberately KEPT (with its unit tests in
tests/unit/test_pr_unapproved_source_guard.py) as the one correct spelling of
the predicate, for a future report or advisory that wants it.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def vendor_acme(db_with_data):
    from app.vendors.models import Vendor
    v = Vendor(code='V902', name='ACME', is_active=True, default_vat_category='V12DG')
    db.session.add(v); db.session.commit()
    return v


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _pr(branch, status, number='BAN-PR-1'):
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 8, 26),
                         branch_id=branch.id, status=status)
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='Cement', quantity=Decimal('10')))
    db.session.add(pr); db.session.commit()
    return pr


def _po(branch, vendor, pr_items=(), status='draft', number='BAN-PO-1'):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 26), status=status,
                       vendor_id=vendor.id, vendor_name=vendor.name, notes='',
                       payment_terms='Net 30', vat_treatment='inclusive',
                       branch_id=branch.id)
    items = list(pr_items) or [None]
    for n, it in enumerate(items, start=1):
        po.line_items.append(PurchaseOrderItem(
            line_number=n, description='Cement', quantity=Decimal('2'),
            unit_price=Decimal('10.00'), amount=Decimal('20.00'),
            line_total=Decimal('20.00'), vat_rate=Decimal('0'),
            vat_amount=Decimal('0'),
            source_pr_item_id=(it.id if it is not None else None)))
    db.session.add(po); db.session.commit()
    return po


def _detail(client, po):
    resp = client.get(f'/purchase-orders/{po.id}')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


class TestTheOrderApproves:

    def test_a_submitted_source_does_not_block_approval(self, client, admin_user,
                                                        branch_manila, vendor_acme,
                                                        db_session):
        """THE POINT of the reversal."""
        pr = _pr(branch_manila, 'submitted', number='NOB-PR-1')
        po = _po(branch_manila, vendor_acme, pr_items=pr.line_items,
                 status='draft', number='NOB-PO-1')
        _login(client, admin_user, branch_manila)
        client.post(f'/purchase-orders/{po.id}/approve')
        db_session.refresh(po)
        assert po.status == 'approved'

    @pytest.mark.parametrize('src_status', ['rejected', 'cancelled'])
    def test_a_rejected_or_cancelled_source_does_not_block_either(
            self, client, admin_user, branch_manila, vendor_acme, db_session,
            src_status):
        """These were the strongest case FOR the old guard -- a requisition
        pulled while submitted can still take either exit, and nothing unwinds
        the order's lines. Recorded here as a deliberate consequence, not an
        oversight."""
        pr = _pr(branch_manila, src_status, number=f'NOB-PR-{src_status}')
        po = _po(branch_manila, vendor_acme, pr_items=pr.line_items,
                 status='draft', number=f'NOB-PO-{src_status}')
        _login(client, admin_user, branch_manila)
        client.post(f'/purchase-orders/{po.id}/approve')
        db_session.refresh(po)
        assert po.status == 'approved'

    def test_an_approved_source_still_approves(self, client, admin_user,
                                               branch_manila, vendor_acme,
                                               db_session):
        """CONTROL -- the ordinary path was never blocked and must still work."""
        pr = _pr(branch_manila, 'approved', number='NOB-PR-OK')
        po = _po(branch_manila, vendor_acme, pr_items=pr.line_items,
                 status='draft', number='NOB-PO-OK')
        _login(client, admin_user, branch_manila)
        client.post(f'/purchase-orders/{po.id}/approve')
        db_session.refresh(po)
        assert po.status == 'approved'


class TestTheBannerIsGone:

    def test_no_banner_is_rendered(self, client, admin_user, branch_manila,
                                   vendor_acme):
        pr = _pr(branch_manila, 'submitted', number='NOB-PR-2')
        po = _po(branch_manila, vendor_acme, pr_items=pr.line_items,
                 number='NOB-PO-2')
        _login(client, admin_user, branch_manila)
        html = _detail(client, po)
        assert 'unapproved-source-alert' not in html
        assert 'has not been approved' not in html
        # CONTROL: the page really did render this order, so the absence above
        # is not an empty-body false pass.
        assert 'NOB-PO-2' in html

    def test_the_approve_button_is_still_offered(self, client, admin_user,
                                                 branch_manila, vendor_acme):
        pr = _pr(branch_manila, 'submitted', number='NOB-PR-3')
        po = _po(branch_manila, vendor_acme, pr_items=pr.line_items,
                 number='NOB-PO-3')
        _login(client, admin_user, branch_manila)
        assert f'/purchase-orders/{po.id}/approve' in _detail(client, po)


class TestThePredicateSurvives:

    def test_unapproved_source_prs_is_still_importable_and_correct(
            self, branch_manila, vendor_acme):
        """Kept on purpose: it is the one correct spelling of "the demand behind
        this line was never authorised". Removing the gate must not delete the
        vocabulary a future report would reuse."""
        from app.purchase_requests.allocation import unapproved_source_prs
        pr = _pr(branch_manila, 'submitted', number='NOB-PR-4')
        po = _po(branch_manila, vendor_acme, pr_items=pr.line_items,
                 number='NOB-PO-4')
        assert [p.id for p in unapproved_source_prs(po)] == [pr.id]
