from decimal import Decimal
from datetime import date
import pytest

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _make_pr(db_session, branch, status='draft', number='PR-2026-07-0300'):
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number, request_date=date(2026, 7, 11),
                         status=status, reason='Site needs cement')
    pr.line_items.append(PurchaseRequestItem(line_number=1, description='Cement',
                                             quantity=Decimal('10'), uom_text='bag'))
    db_session.add(pr); db_session.commit()
    return pr


def test_submit_then_approve(client, accountant_user, main_branch, db_session):
    _login(client, accountant_user, main_branch)
    pr = _make_pr(db_session, main_branch)
    client.post(f'/purchase-requests/{pr.id}/submit')
    db_session.refresh(pr); assert pr.status == 'submitted'
    client.post(f'/purchase-requests/{pr.id}/approve')
    db_session.refresh(pr); assert pr.status == 'approved' and pr.approved_by_id == accountant_user.id


def test_staff_cannot_approve(client, staff_user, main_branch, db_session):
    _login(client, staff_user, main_branch)
    pr = _make_pr(db_session, main_branch, status='submitted')
    client.post(f'/purchase-requests/{pr.id}/approve')
    db_session.refresh(pr); assert pr.status == 'submitted'


def test_reject_requires_reason(client, accountant_user, main_branch, db_session):
    _login(client, accountant_user, main_branch)
    pr = _make_pr(db_session, main_branch, status='submitted')
    client.post(f'/purchase-requests/{pr.id}/reject', data={'reject_reason': 'short'})
    db_session.refresh(pr); assert pr.status == 'submitted'
    client.post(f'/purchase-requests/{pr.id}/reject', data={'reject_reason': 'budget not approved yet'})
    db_session.refresh(pr); assert pr.status == 'rejected'


def test_convert_creates_linked_draft_po(client, accountant_user, main_branch, db_session):
    """The chain-closer: an approved PR converts to a draft PO with copied lines + both links."""
    from app.purchase_orders.models import PurchaseOrder
    from app.audit.models import AuditLog
    _login(client, accountant_user, main_branch)
    pr = _make_pr(db_session, main_branch, status='approved')
    resp = client.post(f'/purchase-requests/{pr.id}/convert', follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(pr)
    assert pr.status == 'converted' and pr.purchase_order_id is not None
    po = db_session.get(PurchaseOrder, pr.purchase_order_id)
    assert po is not None
    assert po.status == 'draft'                       # buyer completes vendor + prices
    assert po.purchase_request_id == pr.id            # back-link
    assert po.vendor_id is None                       # no vendor yet
    assert len(po.line_items) == 1
    assert po.line_items[0].description == 'Cement'
    assert po.line_items[0].quantity == Decimal('10')
    assert po.line_items[0].unit_price is None        # no price copied
    assert AuditLog.query.filter_by(module='purchase_requests', action='convert',
                                    record_id=pr.id).count() == 1


def test_convert_blocked_unless_approved(client, accountant_user, main_branch, db_session):
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    pr = _make_pr(db_session, main_branch, status='draft')     # not approved
    client.post(f'/purchase-requests/{pr.id}/convert')
    db_session.refresh(pr)
    assert pr.status == 'draft' and pr.purchase_order_id is None
    assert PurchaseOrder.query.count() == 0


def test_sidebar_shows_and_hides_pr_link(client, accountant_user, main_branch, db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    _login(client, accountant_user, main_branch)
    body = client.get('/dashboard').data
    assert b'/purchase-requests' in body and b'Purchase Requests' in body
    AppSettings.set_setting('module_enabled:purchase_requests', '0')
    db_session.commit(); clear_module_config_cache()
    assert b'/purchase-requests' not in client.get('/dashboard').data


def test_print_renders(client, accountant_user, main_branch, db_session):
    _login(client, accountant_user, main_branch)
    pr = _make_pr(db_session, main_branch)
    resp = client.get(f'/purchase-requests/{pr.id}/print')
    assert resp.status_code == 200
    assert b'PURCHASE REQUEST' in resp.data and bytes(pr.pr_number, 'utf-8') in resp.data
