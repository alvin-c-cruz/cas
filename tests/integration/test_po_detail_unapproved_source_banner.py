"""The Purchase Order detail page says WHY approval is blocked, before the click.

Task 3 refuses approval while a source requisition is unapproved. Without this
the buyer meets that refusal only by pressing Approve -- and on a multi-line
order has no way to tell which of several requisitions is the problem until the
flash names it.

The banner mirrors the requisition's own pending-amendment alert
(purchase_requests/detail.html): same alert-warning element, same reason, and
notably the same decision to LEAVE THE BUTTON IN PLACE. That is deliberate --
see TestTheApproveButtonStays.
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


class TestTheBannerAppears:

    def test_a_submitted_source_raises_the_banner(self, client, admin_user,
                                                  branch_manila, vendor_acme):
        pr = _pr(branch_manila, 'submitted')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        _login(client, admin_user, branch_manila)
        html = _detail(client, po)
        assert 'unapproved-source-alert' in html
        assert 'alert alert-warning' in html

    def test_the_banner_names_the_requisition_and_its_status(
            self, client, admin_user, branch_manila, vendor_acme):
        """A multi-line order can draw on several requisitions. "a source is
        unapproved" would leave the buyer opening each line to find which."""
        pr = _pr(branch_manila, 'submitted', number='BAN-PR-NAMED')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        _login(client, admin_user, branch_manila)
        html = _detail(client, po)
        assert 'BAN-PR-NAMED' in html
        assert 'submitted' in html

    def test_a_rejected_source_raises_the_banner(self, client, admin_user,
                                                 branch_manila, vendor_acme):
        """The nastiest case: pulled while submitted, rejected afterwards.
        Nothing unwinds the order's lines, so the page has to say so."""
        pr = _pr(branch_manila, 'rejected')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        _login(client, admin_user, branch_manila)
        assert 'unapproved-source-alert' in _detail(client, po)

    def test_a_cancelled_source_raises_the_banner(self, client, admin_user,
                                                  branch_manila, vendor_acme):
        pr = _pr(branch_manila, 'cancelled')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        _login(client, admin_user, branch_manila)
        assert 'unapproved-source-alert' in _detail(client, po)

    def test_two_unapproved_sources_are_both_named(self, client, admin_user,
                                                   branch_manila, vendor_acme):
        a = _pr(branch_manila, 'submitted', number='BAN-PR-A')
        b = _pr(branch_manila, 'rejected', number='BAN-PR-B')
        po = _po(branch_manila, vendor_acme, [a.line_items[0], b.line_items[0]])
        _login(client, admin_user, branch_manila)
        html = _detail(client, po)
        assert 'BAN-PR-A' in html
        assert 'BAN-PR-B' in html

    def test_a_staff_user_sees_it_too(self, client, staff_user, branch_manila,
                                      vendor_acme):
        """Visible to everyone who can open the order, not just approvers -- the
        staff purchaser who pulled the line is the one who has to chase the
        signature, and she is exactly who cannot approve."""
        pr = _pr(branch_manila, 'submitted')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        # The shared staff_user fixture grants the AP/SI-era books but not
        # purchase_orders, and staff are default-deny per module -- without this
        # the page 302s to the module gate and the assertion below would be
        # measuring the redirect, not the banner.
        perms = staff_user.get_book_permissions()
        perms['purchase_orders'] = True
        staff_user.set_book_permissions(perms)
        staff_user.branches.append(branch_manila)
        db.session.commit()
        _login(client, staff_user, branch_manila)
        assert 'unapproved-source-alert' in _detail(client, po)


class TestTheBannerStaysAway:
    """Controls. A banner on a healthy order is noise that trains buyers to
    ignore the real one."""

    def test_an_approved_source_raises_no_banner(self, client, admin_user,
                                                 branch_manila, vendor_acme):
        pr = _pr(branch_manila, 'approved')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        _login(client, admin_user, branch_manila)
        assert 'unapproved-source-alert' not in _detail(client, po)

    def test_a_partially_converted_source_raises_no_banner(
            self, client, admin_user, branch_manila, vendor_acme):
        pr = _pr(branch_manila, 'partially_converted')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        _login(client, admin_user, branch_manila)
        assert 'unapproved-source-alert' not in _detail(client, po)

    def test_an_order_with_no_requisition_source_raises_no_banner(
            self, client, admin_user, branch_manila, vendor_acme):
        """THE control for the services path and every install without the
        requisition module."""
        po = _po(branch_manila, vendor_acme, [])
        _login(client, admin_user, branch_manila)
        assert 'unapproved-source-alert' not in _detail(client, po)

    def test_an_already_approved_order_raises_no_banner(
            self, client, admin_user, branch_manila, vendor_acme):
        """The banner explains why APPROVAL is blocked, so it belongs only in
        the window where approval is still possible. On an approved order it
        would be a warning about nothing the reader can act on -- and a source
        CAN be cancelled after the fact, so this really does occur."""
        pr = _pr(branch_manila, 'cancelled')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]], status='approved')
        _login(client, admin_user, branch_manila)
        assert 'unapproved-source-alert' not in _detail(client, po)


class TestTheApproveButtonStays:
    """The button is NOT hidden, and that is a decision rather than an omission.

    This template elsewhere avoids offering a button the route will refuse (its
    own comments call it "the delete_approved_email shape"). That rule is about
    a PERMANENT dead path -- a control no state of the system can make work.
    This block is transient and is cleared by SOMEBODY ELSE approving the
    requisition, exactly like the requisition's own pending-amendment block,
    which likewise leaves Convert in place (purchase_requests/detail.html:124).

    Hiding it would also read as "you lack permission" to the approver, which is
    the wrong diagnosis: the banner names the real one.
    """

    def test_approve_is_still_offered_with_an_unapproved_source(
            self, client, admin_user, branch_manila, vendor_acme):
        pr = _pr(branch_manila, 'submitted')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        _login(client, admin_user, branch_manila)
        html = _detail(client, po)
        assert f'/purchase-orders/{po.id}/approve' in html

    def test_pressing_it_still_refuses(self, client, admin_user, branch_manila,
                                       vendor_acme):
        """The pairing that makes leaving the button safe: the route is the
        enforcement, the banner is only the explanation."""
        pr = _pr(branch_manila, 'submitted')
        po = _po(branch_manila, vendor_acme, [pr.line_items[0]])
        _login(client, admin_user, branch_manila)
        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert db.session.get(PurchaseOrder, po.id).status == 'draft'
