"""Approving a PO writes Rev 0. A refused approval writes nothing."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders is an optional module (default_enabled=False) -- without this,
    enforce_module_access 404s the route for every role, admin included. Mirrors
    test_purchase_orders_lifecycle.py's identically-named fixture."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def draft_po(db_with_data, branch_manila):
    po = PurchaseOrder(po_number='00998', order_date=date(2026, 8, 5), status='draft',
                       vendor_id=None, vendor_name='ACME', notes='',
                       payment_terms='Net 30', vat_treatment='inclusive',
                       branch_id=branch_manila.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='widget', quantity=Decimal('2'),
        unit_price=Decimal('10.00'), amount=Decimal('20.00'),
        line_total=Decimal('20.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0')))
    db.session.add(po)
    db.session.commit()
    return po


@pytest.fixture
def vendor_acme(db_with_data):
    from app.vendors.models import Vendor
    v = Vendor(code='V900', name='ACME', is_active=True, default_vat_category='V12DG')
    db.session.add(v)
    db.session.commit()
    return v


def _login(client, user, branch):
    """Direct-session login, matching test_purchase_orders_lifecycle.py's convention.

    The conftest `login_user` fixture posts username/password through the real
    /login view, which does not select a branch -- an admin with access to more
    than one active branch (both `main_branch`, pulled in via `db_with_data`, and
    `branch_manila` exist here) would then get redirected to the branch picker by
    the validate_branch_session before_request hook, and the approve POST would
    never reach the view. Setting the session directly, scoped to the PO's own
    branch, is what _get_po_or_404 requires (it 404s unless
    po.branch_id == session['selected_branch_id']).
    """
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _revs(po):
    return DocumentRevision.query.filter_by(
        document_type='purchase_orders', document_id=po.id).all()


class TestRev0OnApprove:
    def test_approval_writes_exactly_one_rev_0(self, client, admin_user, branch_manila,
                                               draft_po, vendor_acme):
        draft_po.vendor_id = vendor_acme.id
        db.session.commit()
        _login(client, admin_user, branch_manila)

        resp = client.post(f'/purchase-orders/{draft_po.id}/approve', follow_redirects=True)
        assert resp.status_code == 200

        revs = _revs(draft_po)
        assert len(revs) == 1
        assert revs[0].revision_number == 0
        assert revs[0].reason is None, 'Rev 0 is a baseline, not an amendment'
        assert revs[0].amended_by_id == admin_user.id

    def test_rev_0_snapshot_records_the_APPROVED_state(self, client, admin_user, branch_manila,
                                                       draft_po, vendor_acme):
        draft_po.vendor_id = vendor_acme.id
        db.session.commit()
        _login(client, admin_user, branch_manila)
        client.post(f'/purchase-orders/{draft_po.id}/approve', follow_redirects=True)

        snap = json.loads(_revs(draft_po)[0].snapshot_json)
        assert snap['header']['status'] == 'approved', 'snapshot must be taken AFTER the status change'
        assert snap['header']['approved_by_id'] == str(admin_user.id)
        assert len(snap['lines']) == 1

    def test_refused_approval_writes_no_revision(self, client, admin_user, branch_manila, draft_po):
        # No vendor set -> approve() refuses. Control: the guard must not leave a revision behind.
        _login(client, admin_user, branch_manila)
        client.post(f'/purchase-orders/{draft_po.id}/approve', follow_redirects=True)

        assert db.session.get(PurchaseOrder, draft_po.id).status == 'draft'
        assert _revs(draft_po) == []

    def test_second_approval_attempt_does_not_add_a_second_rev_0(self, client, admin_user,
                                                                 branch_manila, draft_po, vendor_acme):
        draft_po.vendor_id = vendor_acme.id
        db.session.commit()
        _login(client, admin_user, branch_manila)
        client.post(f'/purchase-orders/{draft_po.id}/approve', follow_redirects=True)
        client.post(f'/purchase-orders/{draft_po.id}/approve', follow_redirects=True)

        assert len(_revs(draft_po)) == 1, 'the not-draft guard must prevent a duplicate baseline'
