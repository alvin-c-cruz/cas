import json
import pytest
from app.settings import AppSettings
from app.sales_invoices.preprinted_layout import LAYOUT_SETTING_KEY, _layout_key

pytestmark = [pytest.mark.integration, pytest.mark.sales_invoices]

URL = '/sales-invoices/print-layout'


def login(client, u='admin', p='admin123'):
    client.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


def test_admin_saves_layout(client, db_session, admin_user, main_branch):
    login(client)
    payload = {'fields': {'invoice_no': {'x': 333, 'y': 44}}}
    resp = client.post(URL, json=payload)
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    # Phase 1: the save route writes the per-branch key (session branch auto-selected
    # to the user's single branch), not the legacy global key.
    stored = json.loads(AppSettings.get_setting(_layout_key(main_branch.id)))
    assert stored['fields']['invoice_no']['x'] == 333


def test_a_viewer_is_forbidden(client, db_session, viewer_user, main_branch):
    """the negative case is now `viewer`: staff and accountants may edit layouts since 2026-08-26 (owner decision), so a staff-based refusal test would pin the OLD rule -- an accountant now saves successfully, so this pinned the old rule."""
    login(client, 'viewer', 'viewer123')
    resp = client.post(URL, json={'fields': {}})
    assert resp.status_code in (302, 403)               # gated
    assert AppSettings.get_setting(LAYOUT_SETTING_KEY) is None   # nothing written


def test_anonymous_redirected(client, db_session):
    resp = client.post(URL, json={'fields': {}})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_garbage_body_still_stores_sanitized_default(client, db_session, admin_user, main_branch):
    login(client)
    resp = client.post(URL, json={'fields': {'evil': {'x': 1}}, 'lineItems': 'not-a-dict'})
    assert resp.status_code == 200
    stored = json.loads(AppSettings.get_setting(_layout_key(main_branch.id)))
    assert 'evil' not in stored['fields']
    assert isinstance(stored['lineItems']['columns'], list)


# ---------------------------------------------------------------------------
# Task 5 review defect (Finding 1): save_print_layout is branchless -- it has
# no invoice id and previously trusted session['selected_branch_id'] alone.
# print_invoice now follows branch ACCESS, not the selected branch, and the
# only thing that kept the layout write scoped to the right branch was a
# render-time UI gate (can_edit_layout). If the user's selected branch
# changes between render and the AJAX POST (e.g. a second tab switches
# branch), the write must be refused server-side, not silently accepted
# under the (now wrong) selected branch's key.
# ---------------------------------------------------------------------------

def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def test_mismatched_branch_id_rejected(client, db_session, admin_user, main_branch, branch_manila):
    login(client)
    _select_branch(client, main_branch.id)
    payload = {'branchId': branch_manila.id, 'fields': {'invoice_no': {'x': 333, 'y': 44}}}
    resp = client.post(URL, json=payload)
    assert resp.status_code == 409
    body = resp.get_json()
    assert body['ok'] is False
    # nothing written under either branch's key
    assert AppSettings.get_setting(_layout_key(main_branch.id)) is None
    assert AppSettings.get_setting(_layout_key(branch_manila.id)) is None


def test_matching_branch_id_accepted(client, db_session, admin_user, main_branch, branch_manila):
    login(client)
    _select_branch(client, main_branch.id)
    payload = {'branchId': main_branch.id, 'fields': {'invoice_no': {'x': 333, 'y': 44}}}
    resp = client.post(URL, json=payload)
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    stored = json.loads(AppSettings.get_setting(_layout_key(main_branch.id)))
    assert stored['fields']['invoice_no']['x'] == 333


def test_missing_branch_id_still_accepted(client, db_session, admin_user, main_branch, branch_manila):
    """An older cached designer page (pre-fix JS) posts without `branchId` at
    all. Treated conservatively as "no assertion made" rather than rejected --
    this preserves the exact pre-fix behavior (write under the selected
    branch's key) for that one case, rather than breaking a legitimate stale
    client outright. A present-but-WRONG branchId is the case this fix closes."""
    login(client)
    _select_branch(client, main_branch.id)
    payload = {'fields': {'invoice_no': {'x': 333, 'y': 44}}}
    resp = client.post(URL, json=payload)
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    stored = json.loads(AppSettings.get_setting(_layout_key(main_branch.id)))
    assert stored['fields']['invoice_no']['x'] == 333
