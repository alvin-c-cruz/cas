"""Regression tests for BUG-PR-NUMBER-HARDCODED: pr_number must be user-editable on create,
mirroring PurchaseOrderForm.po_number (app/purchase_orders/forms.py)."""
import json
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


def test_create_pr_honors_submitted_pr_number(client, accountant_user, db_session, main_branch):
    from app.purchase_requests.models import PurchaseRequest
    _login(client, accountant_user, main_branch)
    custom_number = 'PR-CUSTOM-9001'
    resp = client.post('/purchase-requests/create', data={
        'request_date': '2026-07-17',
        'reason': 'Test requisition',
        'line_items': json.dumps([{"description": "Test item", "quantity": 5}]),
        'pr_number': custom_number,
    }, follow_redirects=True)
    assert resp.status_code == 200
    pr = PurchaseRequest.query.filter_by(pr_number=custom_number).first()
    assert pr is not None, 'submitted pr_number was not honored (still auto-generated)'


def test_create_pr_rejects_duplicate_pr_number(client, accountant_user, db_session, main_branch):
    from datetime import date
    from app.purchase_requests.models import PurchaseRequest
    _login(client, accountant_user, main_branch)
    existing = PurchaseRequest(pr_number='PR-DUP-0001', branch_id=main_branch.id,
                               request_date=date(2026, 7, 16), status='draft')
    db_session.add(existing)
    db_session.commit()

    resp = client.post('/purchase-requests/create', data={
        'request_date': '2026-07-17',
        'reason': 'Test requisition',
        'line_items': json.dumps([{"description": "Test item", "quantity": 5}]),
        'pr_number': 'PR-DUP-0001',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'already exists' in resp.data
    assert PurchaseRequest.query.filter_by(pr_number='PR-DUP-0001').count() == 1


def test_create_pr_get_prefills_generated_number(client, accountant_user, main_branch):
    _login(client, accountant_user, main_branch)
    resp = client.get('/purchase-requests/create')
    assert resp.status_code == 200
    assert b'name="pr_number"' in resp.data
