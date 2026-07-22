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


def _create(client, lines=None, reason='Site needs cement', pr_number=None):
    if lines is None:
        lines = [{'product_id': None, 'description': 'Cement', 'quantity': '10', 'uom_text': 'bag'}]
    if pr_number is None:
        from app.purchase_requests.models import generate_pr_number
        pr_number = generate_pr_number()
    return client.post('/purchase-requests/create', data={
        'request_date': '2026-07-11', 'reason': reason,
        'line_items': json.dumps(lines),
        'pr_number': pr_number,
    }, follow_redirects=True)


def test_create_pr_persists_and_audits(client, accountant_user, main_branch, db_session):
    from app.purchase_requests.models import PurchaseRequest
    from app.audit.models import AuditLog
    _login(client, accountant_user, main_branch)
    resp = _create(client)
    assert resp.status_code == 200
    pr = PurchaseRequest.query.first()
    assert pr is not None and pr.status == 'draft' and pr.branch_id == main_branch.id
    assert pr.reason == 'Site needs cement'
    assert len(pr.line_items) == 1 and pr.line_items[0].description == 'Cement'
    assert AuditLog.query.filter_by(module='purchase_requests', action='create',
                                    record_id=pr.id).count() == 1


def test_create_pr_posts_no_journal_entry(client, accountant_user, main_branch, db_session):
    from app.journal_entries.models import JournalEntry
    before = JournalEntry.query.count()
    _login(client, accountant_user, main_branch)
    _create(client)
    assert JournalEntry.query.count() == before


def test_line_requires_product_or_description(client, accountant_user, main_branch, db_session):
    from app.purchase_requests.models import PurchaseRequest
    _login(client, accountant_user, main_branch)
    resp = _create(client, lines=[{'product_id': None, 'description': '', 'quantity': '5'}])
    assert resp.status_code == 200
    assert PurchaseRequest.query.count() == 0


def test_list_and_view_show_pr(client, accountant_user, main_branch, db_session):
    from app.purchase_requests.models import PurchaseRequest
    _login(client, accountant_user, main_branch)
    _create(client)
    pr = PurchaseRequest.query.first()
    assert bytes(pr.pr_number, 'utf-8') in client.get('/purchase-requests').data
    assert client.get(f'/purchase-requests/{pr.id}').status_code == 200


def test_page_title_not_dashboard(client, accountant_user, main_branch, db_session):
    """Regression (BUG-PURCHASES-PAGE-TITLE-DASHBOARD): list/detail/form must set their
    own page_title block, not fall through to base.html's default "Dashboard"."""
    from app.purchase_requests.models import PurchaseRequest
    _login(client, accountant_user, main_branch)
    _create(client)
    pr = PurchaseRequest.query.first()

    list_body = client.get('/purchase-requests').data.decode('utf-8')
    assert 'Purchase Requests' in list_body

    detail_body = client.get(f'/purchase-requests/{pr.id}').data.decode('utf-8')
    assert f'Purchase Request — {pr.pr_number}' in detail_body

    create_body = client.get('/purchase-requests/create').data.decode('utf-8')
    assert 'Enter Purchase Request' in create_body


def test_detail_page_shows_created_by(client, accountant_user, main_branch, db_session):
    _login(client, accountant_user, main_branch)
    _create(client)
    from app.purchase_requests.models import PurchaseRequest
    pr = PurchaseRequest.query.first()
    resp = client.get(f'/purchase-requests/{pr.id}')
    assert b'Created by' in resp.data
    assert b'accountant' in resp.data


def test_create_form_loads_search_select_for_product_picker(client, accountant_user, main_branch, db_session):
    """BUG-PR-PRODUCT-PICKER-NOT-CHOICES: PR's product picker must use the shared Choices.js
    search-select pattern, like every other product picker in the app."""
    _login(client, accountant_user, main_branch)
    resp = client.get('/purchase-requests/create')
    assert resp.status_code == 200
    assert b'search-select.js' in resp.data
    assert b'choices.min.js' in resp.data
    assert b'initSearchSelect' in resp.data
