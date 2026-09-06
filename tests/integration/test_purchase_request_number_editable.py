"""Regression tests for BUG-PR-NUMBER-HARDCODED: pr_number must be user-editable on create,
mirroring PurchaseOrderForm.po_number (app/purchase_orders/forms.py)."""
import json
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


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


# ---------------------------------------------------------------------------
# The EDIT path. Found 2026-09-06 while correcting a live requisition whose
# number had been auto-generated wrongly (00001 instead of the client's 25-NNNN
# series): the field renders, accepts a new number and flashes "updated", but
# edit() never assigned pr.pr_number, so the change was silently discarded.
# Every test above this line exercises CREATE only, which is how it survived.
# ---------------------------------------------------------------------------

def _draft(db_session, branch, number='PR-EDIT-0001'):
    from datetime import date
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    pr = PurchaseRequest(pr_number=number, branch_id=branch.id,
                         request_date=date(2026, 9, 6), status='draft',
                         reason='Site needs cement')
    pr.line_items.append(PurchaseRequestItem(line_number=1, description='Cement',
                                             quantity=5))
    db_session.add(pr); db_session.commit()
    return pr


def _edit(client, pr, number):
    # row_version is REQUIRED: submitted_version() reads the raw POST body and
    # claim_version(None) is False, so an edit posted without the token bails at
    # the optimistic-locking gate before any field is assigned. Omitting it made
    # the two "number is unchanged" tests below pass VACUOUSLY -- they were
    # observing a refused edit, not a preserved number.
    return client.post(f'/purchase-requests/{pr.id}/edit', data={
        'request_date': '2026-09-06',
        'reason': 'Site needs cement',
        'line_items': json.dumps([{"description": "Cement", "quantity": 5}]),
        'pr_number': number,
        'row_version': pr.row_version,
    }, follow_redirects=True)


def test_edit_pr_honors_a_changed_pr_number(client, accountant_user, db_session,
                                            main_branch):
    _login(client, accountant_user, main_branch)
    pr = _draft(db_session, main_branch, number='00001')
    resp = _edit(client, pr, '25-0973')
    assert resp.status_code == 200
    db_session.refresh(pr)
    assert pr.pr_number == '25-0973', (
        'the submitted pr_number was discarded -- edit() never assigned it')


def test_edit_pr_rejects_a_duplicate_number(client, accountant_user, db_session,
                                            main_branch):
    """The create path refuses a collision; the edit path must too, or the
    unique index turns a typo into an IntegrityError 500."""
    from app.purchase_requests.models import PurchaseRequest
    _login(client, accountant_user, main_branch)
    _draft(db_session, main_branch, number='25-0914')
    pr = _draft(db_session, main_branch, number='00001')
    resp = _edit(client, pr, '25-0914')
    assert resp.status_code == 200
    assert b'already exists' in resp.data               # refused BY NAME...
    db_session.refresh(pr)
    assert pr.pr_number == '00001'                      # ...and left unchanged
    assert PurchaseRequest.query.filter_by(pr_number='25-0914').count() == 1


def test_edit_pr_keeps_its_number_when_unchanged(client, accountant_user,
                                                 db_session, main_branch):
    """CONTROL: resubmitting the SAME number must not trip the duplicate check
    against the requisition's own row."""
    _login(client, accountant_user, main_branch)
    pr = _draft(db_session, main_branch, number='25-0980')
    resp = _edit(client, pr, '25-0980')
    assert resp.status_code == 200
    db_session.refresh(pr)
    assert pr.pr_number == '25-0980'
