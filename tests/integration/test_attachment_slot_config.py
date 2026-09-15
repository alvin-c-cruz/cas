"""Per-company required-attachment overrides (Company Settings, task 4).

The code seed marks a slot required; an owner can flip that per company via the
AppSettings-backed override, and the completeness resolver must honour it.
"""
from types import SimpleNamespace

import pytest

from app.attachments.completeness import required_slots, visible_slots
from app.attachments import config_overrides
from app.settings import AppSettings
from app import db

pytestmark = [pytest.mark.integration, pytest.mark.attachments]


def _login(client, branch, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def test_override_makes_a_seeded_required_slot_optional(client, db_session, admin_user):
    # Seed: PO vendor_quotation is required.
    doc = SimpleNamespace()
    assert 'vendor_quotation' in [s.key for s in required_slots('purchase_orders', doc)]

    # Owner un-requires it for this company.
    AppSettings.set_setting(config_overrides.required_key('purchase_orders', 'vendor_quotation'), '0')
    db.session.commit()
    assert 'vendor_quotation' not in [s.key for s in required_slots('purchase_orders', doc)]
    # signed_po stays required.
    assert 'signed_po' in [s.key for s in required_slots('purchase_orders', doc)]


def test_hidden_override_drops_slot_from_visible(client, db_session, admin_user):
    doc = SimpleNamespace()
    assert 'vendor_dr_sr' in [s.key for s in visible_slots('receiving_reports', doc)]
    AppSettings.set_setting(config_overrides.hidden_key('receiving_reports', 'vendor_dr_sr'), '1')
    db.session.commit()
    assert 'vendor_dr_sr' not in [s.key for s in visible_slots('receiving_reports', doc)]


def test_settings_page_renders_and_saves(client, db_session, admin_user, main_branch):
    _login(client, main_branch)
    resp = client.get('/settings/attachment-slots')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Required Attachments' in body
    assert 'Signed PR' in body and 'Vendor Quotation' in body and 'Signed AP' in body

    # Save with vendor_quotation unchecked (absent) → stored as not required.
    resp = client.post('/settings/attachment-slots', data={
        'required:purchase_orders:signed_po': 'on',
        # vendor_quotation intentionally omitted → unchecked
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting(config_overrides.required_key('purchase_orders', 'vendor_quotation')) == '0'
    assert AppSettings.get_setting(config_overrides.required_key('purchase_orders', 'signed_po')) == '1'
