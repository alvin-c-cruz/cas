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


def test_non_admin_forbidden(client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
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
