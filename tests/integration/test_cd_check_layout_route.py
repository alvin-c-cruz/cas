"""Integration tests for the CDV check-layout SAVE route (`save_cd_check_layout`).

The check overlay is keyed per cash/bank account (?account_id=<id>), omitting it edits
the Default. The in-page print/designer surface is covered by test_cd_check_print.py;
this covers the persistence route only.
"""
import json
import pytest

from app.settings import AppSettings
from app.cash_disbursements.check_layout import LAYOUT_SETTING_KEY

pytestmark = [pytest.mark.cash_disbursements, pytest.mark.integration]

URL = '/cash-disbursements/check-layout'


def login(client, u='admin', p='admin123'):
    client.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


def test_full_access_required(client, db_session, staff_user, main_branch):
    staff_user.set_branches([main_branch]); db_session.commit()
    login(client, 'staff', 'staff123')
    resp = client.post(URL, json={'fields': {'payee': {'x': 200, 'y': 200}}})
    assert resp.status_code == 403


def test_anonymous_redirected(client, db_session):
    resp = client.post(URL, json={'fields': {}})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_admin_saves_default_layout_sanitized(client, db_session, admin_user, main_branch):
    login(client)
    resp = client.post(URL, json={'fields': {'payee': {'x': 321, 'y': 88}}, 'evil': 'nope'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert data['layout']['fields']['payee']['x'] == 321
    assert 'evil' not in data['layout']
    # persisted under the Default key (no account_id)
    stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
    assert stored['fields']['payee']['x'] == 321


def test_admin_saves_per_account_layout(client, db_session, admin_user, main_branch):
    login(client)
    resp = client.post(URL + '?account_id=7',
                       json={'fields': {'payee': {'x': 210, 'y': 90}}})
    assert resp.status_code == 200
    # persisted under the account-scoped key, not the Default
    assert json.loads(AppSettings.get_setting(f'{LAYOUT_SETTING_KEY}:7'))['fields']['payee']['x'] == 210
    assert AppSettings.get_setting(LAYOUT_SETTING_KEY) is None


def test_field_width_roundtrips(client, db_session, admin_user, main_branch):
    login(client)
    resp = client.post(URL, json={'fields': {'amount_in_words': {'x': 80, 'y': 232, 'width': 620}}})
    assert resp.status_code == 200
    assert resp.get_json()['layout']['fields']['amount_in_words']['width'] == 620
