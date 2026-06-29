"""Integration tests for the master-data change-request workflow (B-006).

Covers Chart of Accounts, VAT Categories and Withholding Tax:
- "Reason for change" is required and persisted on EDIT and DELETE change
  requests; CREATE is exempt (nothing is being changed — the reviewer judges
  the proposed data), so the create form omits the field entirely
- Duplicate pending requests for the same record are blocked
- Submission feedback flash is shown
- Audit entries are written with the correct action, record reference and actor
"""
import html
import json
from pathlib import Path

import pytest

from app.accounts.models import Account
from app.accounts.approval_models import AccountChangeRequest
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
from app.withholding_tax.models import WithholdingTax, WithholdingTaxChangeRequest
from app.audit.models import AuditLog
from app.utils import ph_now
pytestmark = [pytest.mark.accounts, pytest.mark.integration]




PENDING_FLASH = b'Change request submitted'
DUPLICATE_FLASH = b'A pending change request for this record already exists'


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def two_reviewers(admin_user, db_session, main_branch):
    """Two active admin users so sole_admin_can_auto_approve() is False.

    VAT Categories and Withholding Tax are now admin-only (sole-admin auto-approves).
    With two admins, all creates/updates go to a pending change request.
    A branch must exist for login to succeed.
    """
    from app.users.models import User
    second_admin = User(username='admin2', email='admin2@example.com',
                        full_name='Second Admin', role='admin', is_active=True)
    second_admin.set_password('admin2pass')
    db_session.add(second_admin)
    db_session.commit()
    return admin_user, second_admin


# ───────────────────────── VAT Categories ─────────────────────────

def make_vat(db_session, code='VAT12', name='VATable 12%'):
    vat = VATCategory(code=code, name=name, rate=12.00, is_active=True)
    db_session.add(vat)
    db_session.commit()
    return vat


def make_input_vat_account(db_session, code='10599', name='Input VAT'):
    """A leaf asset account usable as the Input Tax account (B-014)."""
    account = Account(code=code, name=name, account_type='Asset',
                      normal_balance='Debit', is_active=True)
    db_session.add(account)
    db_session.commit()
    return account


def vat_form_data(code='VATX', name='Test VAT', reason='Needed for BIR compliance',
                  input_vat_account_id=None):
    data = {
        'code': code,
        'name': name,
        'description': 'test',
        'rate': '12.00',
        'is_active': '1',
    }
    if input_vat_account_id is not None:
        data['input_vat_account_id'] = str(input_vat_account_id)
        # rate > 0 now also requires an output tax account; reuse the same leaf
        # account (the VAT pickers accept any active leaf account).
        data['output_vat_account_id'] = str(input_vat_account_id)
    if reason is not None:
        data['request_reason'] = reason
    return data


class TestVATCategoryChangeRequests:
    def test_create_persists_reason_flash_and_audit(self, client, db_session, two_reviewers):
        login(client)
        input_vat = make_input_vat_account(db_session)
        resp = client.post('/vat-categories/create',
                           data=vat_form_data(reason='New VAT type required',
                                              input_vat_account_id=input_vat.id),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert PENDING_FLASH in resp.data

        requests = VATCategoryChangeRequest.query.all()
        assert len(requests) == 1
        cr = requests[0]
        assert cr.status == 'pending'

        audit = AuditLog.query.filter_by(module='vat_category', action='create',
                                         record_id=cr.id).first()
        assert audit is not None
        assert 'VATX' in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id

    def test_create_does_not_require_reason(self, client, db_session, two_reviewers):
        """Creating master data needs no reason — the reviewer judges the proposed data."""
        login(client)
        input_vat = make_input_vat_account(db_session)
        resp = client.post('/vat-categories/create',
                           data=vat_form_data(reason=None,
                                              input_vat_account_id=input_vat.id),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert PENDING_FLASH in resp.data
        assert VATCategoryChangeRequest.query.count() == 1

    def test_duplicate_pending_create_is_blocked(self, client, db_session, two_reviewers):
        login(client)
        input_vat = make_input_vat_account(db_session)
        client.post('/vat-categories/create',
                    data=vat_form_data(input_vat_account_id=input_vat.id),
                    follow_redirects=True)
        assert VATCategoryChangeRequest.query.count() == 1

        resp = client.post('/vat-categories/create',
                           data=vat_form_data(input_vat_account_id=input_vat.id),
                           follow_redirects=True)
        assert DUPLICATE_FLASH in resp.data
        assert VATCategoryChangeRequest.query.count() == 1

    def test_duplicate_pending_update_is_blocked(self, client, db_session, two_reviewers):
        login(client)
        vat = make_vat(db_session)
        input_vat = make_input_vat_account(db_session)
        # First update request goes through
        resp = client.post(f'/vat-categories/{vat.id}/edit',
                           data=vat_form_data(code=vat.code, name='Renamed VAT',
                                              input_vat_account_id=input_vat.id),
                           follow_redirects=True)
        assert PENDING_FLASH in resp.data
        assert VATCategoryChangeRequest.query.count() == 1

        # Second one targeting the same record is blocked
        resp = client.post(f'/vat-categories/{vat.id}/edit',
                           data=vat_form_data(code=vat.code, name='Renamed Again',
                                              input_vat_account_id=input_vat.id),
                           follow_redirects=True)
        assert DUPLICATE_FLASH in resp.data
        assert VATCategoryChangeRequest.query.count() == 1

    def test_delete_requires_reason(self, client, db_session, two_reviewers):
        login(client)
        vat = make_vat(db_session)
        resp = client.post(f'/vat-categories/{vat.id}/delete', data={},
                           follow_redirects=True)
        assert b'reason for the change is required' in resp.data
        assert VATCategoryChangeRequest.query.count() == 0

    def test_delete_persists_reason_and_audit(self, client, db_session, two_reviewers):
        login(client)
        vat = make_vat(db_session)
        resp = client.post(f'/vat-categories/{vat.id}/delete',
                           data={'request_reason': 'Obsolete category'},
                           follow_redirects=True)
        assert PENDING_FLASH in resp.data

        cr = VATCategoryChangeRequest.query.one()
        assert cr.action == 'delete'
        assert cr.status == 'pending'
        assert cr.request_reason == 'Obsolete category'

        audit = AuditLog.query.filter_by(module='vat_category', action='delete',
                                         record_id=cr.id).first()
        assert audit is not None
        assert vat.code in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id

    def test_list_shows_pending_badge(self, client, db_session, two_reviewers):
        login(client)
        vat = make_vat(db_session)
        cr = VATCategoryChangeRequest(
            action='update', status='pending', vat_category_id=vat.id,
            proposed_data=json.dumps({'code': vat.code, 'name': 'X', 'rate': 12.0}),
            requested_by_id=two_reviewers[1].id, requested_at=ph_now(),
            request_reason='test')
        db_session.add(cr)
        db_session.commit()

        resp = client.get('/vat-categories/')
        assert resp.status_code == 200
        assert b'Pending change' in resp.data

    def test_reviewer_sees_reason(self, client, db_session, two_reviewers):
        # Request submitted by the accountant; admin reviews it
        login(client)
        vat = make_vat(db_session)
        cr = VATCategoryChangeRequest(
            action='update', status='pending', vat_category_id=vat.id,
            proposed_data=json.dumps({'code': vat.code, 'name': 'X', 'rate': 12.0}),
            requested_by_id=two_reviewers[1].id, requested_at=ph_now(),
            request_reason='Rate change mandated by BIR')
        db_session.add(cr)
        db_session.commit()

        resp = client.get('/vat-categories/change-requests')
        assert b'Rate change mandated by BIR' in resp.data

        resp = client.get(f'/vat-categories/change-requests/{cr.id}/review')
        assert b'Rate change mandated by BIR' in resp.data


# ───────────────────────── Withholding Tax ─────────────────────────

def make_wht(db_session, code='WC010', name='Professional fees'):
    wht = WithholdingTax(code=code, name=name, rate=10.00, is_active=True)
    db_session.add(wht)
    db_session.commit()
    return wht


def wht_form_data(code='WCX', name='Test WHT', reason='Needed for BIR compliance'):
    data = {
        'code': code,
        'name': name,
        'description': 'test',
        'rate': '2.00',
        'is_active': '1',
        'payable_account_id': '0',
        'receivable_account_id': '0',
    }
    if reason is not None:
        data['request_reason'] = reason
    return data


class TestWithholdingTaxChangeRequests:
    def test_create_persists_reason_flash_and_audit(self, client, db_session, two_reviewers):
        login(client)
        resp = client.post('/withholding-tax/create',
                           data=wht_form_data(reason='New WHT code required'),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert PENDING_FLASH in resp.data

        cr = WithholdingTaxChangeRequest.query.one()
        assert cr.status == 'pending'

        audit = AuditLog.query.filter_by(module='withholding_tax', action='create',
                                         record_id=cr.id).first()
        assert audit is not None
        assert 'WCX' in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id

    def test_create_does_not_require_reason(self, client, db_session, two_reviewers):
        """Creating master data needs no reason — the reviewer judges the proposed data."""
        login(client)
        resp = client.post('/withholding-tax/create',
                           data=wht_form_data(reason=None),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert PENDING_FLASH in resp.data
        assert WithholdingTaxChangeRequest.query.count() == 1

    def test_duplicate_pending_create_is_blocked(self, client, db_session, two_reviewers):
        login(client)
        client.post('/withholding-tax/create', data=wht_form_data(), follow_redirects=True)
        assert WithholdingTaxChangeRequest.query.count() == 1

        resp = client.post('/withholding-tax/create', data=wht_form_data(),
                           follow_redirects=True)
        assert DUPLICATE_FLASH in resp.data
        assert WithholdingTaxChangeRequest.query.count() == 1

    def test_duplicate_pending_update_is_blocked(self, client, db_session, two_reviewers):
        login(client)
        wht = make_wht(db_session)
        resp = client.post(f'/withholding-tax/{wht.id}/edit',
                           data=wht_form_data(code=wht.code, name='Renamed WHT'),
                           follow_redirects=True)
        assert PENDING_FLASH in resp.data
        assert WithholdingTaxChangeRequest.query.count() == 1

        resp = client.post(f'/withholding-tax/{wht.id}/edit',
                           data=wht_form_data(code=wht.code, name='Renamed Again'),
                           follow_redirects=True)
        assert DUPLICATE_FLASH in resp.data
        assert WithholdingTaxChangeRequest.query.count() == 1

    def test_delete_requires_reason(self, client, db_session, two_reviewers):
        login(client)
        wht = make_wht(db_session)
        resp = client.post(f'/withholding-tax/{wht.id}/delete', data={},
                           follow_redirects=True)
        assert b'reason for the change is required' in resp.data
        assert WithholdingTaxChangeRequest.query.count() == 0

    def test_delete_persists_reason_and_audit(self, client, db_session, two_reviewers):
        login(client)
        wht = make_wht(db_session)
        resp = client.post(f'/withholding-tax/{wht.id}/delete',
                           data={'request_reason': 'Obsolete code'},
                           follow_redirects=True)
        assert PENDING_FLASH in resp.data

        cr = WithholdingTaxChangeRequest.query.one()
        assert cr.action == 'delete'
        assert cr.request_reason == 'Obsolete code'

        audit = AuditLog.query.filter_by(module='withholding_tax', action='delete',
                                         record_id=cr.id).first()
        assert audit is not None
        assert wht.code in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id

    def test_list_shows_pending_badge(self, client, db_session, two_reviewers):
        login(client)
        wht = make_wht(db_session)
        cr = WithholdingTaxChangeRequest(
            action='update', status='pending', withholding_tax_id=wht.id,
            proposed_data=json.dumps({'code': wht.code, 'name': 'X', 'rate': 10.0}),
            requested_by_id=two_reviewers[1].id, requested_at=ph_now(),
            request_reason='test')
        db_session.add(cr)
        db_session.commit()

        resp = client.get('/withholding-tax/')
        assert resp.status_code == 200
        assert b'Pending change' in resp.data


class TestWithholdingTaxLabels:
    """BIR terminology: page is 'Withholding Tax Expanded' (EWT); code column is 'ATC'."""

    def test_list_page_uses_expanded_label(self, client, db_session, two_reviewers):
        login(client)
        make_wht(db_session)
        resp = client.get('/withholding-tax/')
        assert resp.status_code == 200
        assert b'Withholding Tax Expanded' in resp.data
        assert b'Manage Philippine BIR Expanded Withholding Alphanumeric Tax Codes' in resp.data
        assert b'+ New ATC' in resp.data
        assert b'+ New Withholding Tax' not in resp.data
        assert b'Withholding Tax Codes' not in resp.data

    def test_empty_state_no_cta(self, client, db_session, two_reviewers):
        """With no codes, the empty state shows only a plain message — no CTA button."""
        login(client)
        resp = client.get('/withholding-tax/')
        assert resp.status_code == 200
        assert b'No withholding tax codes found' in resp.data
        assert b'+ Create First' not in resp.data

    def test_list_table_uses_atc_header(self, client, db_session, two_reviewers):
        login(client)
        make_wht(db_session)
        resp = client.get('/withholding-tax/')
        assert b'<th>ATC</th>' in resp.data
        assert b'<th>Code</th>' not in resp.data

    def test_maintenance_nav_uses_expanded_label(self, client, db_session, two_reviewers):
        """Only the Maintenance nav item is renamed; the BIR-Reports one stays 'Withholding Tax'."""
        login(client)
        resp = client.get('/withholding-tax/')
        assert b'<span class="nav-text">Withholding Tax Expanded</span>' in resp.data
        assert b'<span class="nav-text">Withholding Tax</span>' in resp.data

    def test_create_form_uses_atc_field_label(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/withholding-tax/create')
        assert resp.status_code == 200
        assert b'>ATC<' in resp.data
        assert b'WT Code' not in resp.data

    def test_change_requests_back_link_uses_expanded_label(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/withholding-tax/change-requests')
        assert resp.status_code == 200
        assert b'Back to Withholding Tax Expanded' in resp.data
        assert b'Back to Withholding Tax Codes' not in resp.data


CAS_UI_JS = Path(__file__).resolve().parents[2] / 'app' / 'static' / 'js' / 'cas-ui.js'


class TestStatusToggleControl:
    """The Status control is a <select> (Active/Inactive); a <select> has no
    `.checked`, so the toggle visual/label must be driven by its `.value`.
    Regression guard for the broken `this.checked` wiring (FINDING-001).

    The toggle was extracted into a shared component: markup via the
    status_toggle() macro, behaviour wired by initStatusToggle() in cas-ui.js.
    Both WHT and VAT Categories forms are driven by that shared JS."""

    def test_shared_toggle_js_driven_by_select_value(self):
        # The shared behaviour lives in cas-ui.js — guard the FINDING-001 fix there.
        js = CAS_UI_JS.read_text(encoding='utf-8')
        # broken pattern: <select>.checked is always undefined → label stuck on Inactive
        assert "this.checked ? 'Active'" not in js
        # fixed pattern: derive state from the select's value
        assert "input.value === '1'" in js

    def test_wht_create_form_uses_shared_toggle(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/withholding-tax/create')
        assert resp.status_code == 200
        # Renders the shared toggle markup (the macro) and loads the shared JS,
        # rather than re-inlining its own toggle script.
        assert b'class="toggle-input"' in resp.data
        assert b'class="toggle-switch' in resp.data
        assert b'cas-ui.js' in resp.data
        # The old inline wiring must not have crept back into the template.
        assert b".value === '1'" not in resp.data

    def test_vat_create_form_toggle_driven_by_select_value(self, client, db_session, two_reviewers):
        # VAT Categories now uses the shared component (migrated from inline JS).
        login(client)
        resp = client.get('/vat-categories/create')
        assert resp.status_code == 200
        assert b'class="toggle-input"' in resp.data
        assert b'class="toggle-switch' in resp.data
        assert b'cas-ui.js' in resp.data
        assert b".value === '1'" not in resp.data  # inline JS must be gone
        assert b"this.checked ? 'Active'" not in resp.data


class TestWithholdingTaxFlashTerminology:
    """Duplicate-check and success flashes must use WHT/ATC terminology, not the
    'VAT code'/'VAT name'/lowercase text copy-pasted from vat_categories
    (FINDING-003 / FINDING-004)."""

    def test_duplicate_code_flash_uses_atc_terminology(self, client, db_session, two_reviewers):
        login(client)
        make_wht(db_session, code='WC010', name='Professional fees')
        resp = client.post('/withholding-tax/create',
                           data=wht_form_data(code='WC010', name='A different name'),
                           follow_redirects=True)
        assert resp.status_code == 200
        # Jinja autoescapes the quotes in the flash text, so unescape before matching.
        body = html.unescape(resp.data.decode())
        assert 'VAT code' not in body
        assert 'ATC "WC010" already exists' in body

    def test_duplicate_name_flash_uses_withholding_terminology(self, client, db_session, two_reviewers):
        login(client)
        make_wht(db_session, code='WC010', name='Professional fees')
        resp = client.post('/withholding-tax/create',
                           data=wht_form_data(code='WCNEW', name='Professional fees'),
                           follow_redirects=True)
        assert resp.status_code == 200
        body = html.unescape(resp.data.decode())
        assert 'VAT name' not in body
        assert 'Withholding tax name "Professional fees" already exists' in body

    def test_auto_approved_create_success_flash_is_capitalized(self, client, db_session,
                                                               admin_user, main_branch):
        # Sole active admin => sole_admin_can_auto_approve() is True => direct create.
        login(client, username='admin', password='admin123')
        resp = client.post('/withholding-tax/create',
                           data=wht_form_data(code='WCX', name='Test WHT'),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert WithholdingTax.query.filter_by(code='WCX').count() == 1
        body = html.unescape(resp.data.decode())
        assert 'Withholding tax "Test WHT" has been created successfully' in body
        assert 'withholding tax "Test WHT"' not in body  # lowercase variant gone


# ───────────────────────── Chart of Accounts ─────────────────────────

def make_account(db_session, code='1900', name='Test Asset Account'):
    account = Account(code=code, name=name, account_type='Asset',
                      normal_balance='debit', description='test')
    db_session.add(account)
    db_session.commit()
    return account


def account_form_data(code='1901', name='New Test Account',
                      reason='Needed for new asset class'):
    data = {
        'code': code,
        'name': name,
        'account_type': 'Asset',
        'classification': 'Current',
        'normal_balance': 'debit',
        'parent_id': '',
        'description': 'test',
    }
    if reason is not None:
        data['request_reason'] = reason
    return data


class TestAccountChangeRequests:
    def test_create_persists_reason_flash_and_audit(self, client, db_session, two_reviewers):
        login(client)
        resp = client.post('/accounts/create',
                           data=account_form_data(reason='Adding petty cash account'),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert PENDING_FLASH in resp.data

        cr = AccountChangeRequest.query.one()
        assert cr.status == 'pending'
        assert cr.change_type == 'create'

        audit = AuditLog.query.filter_by(module='account', action='create',
                                         record_id=cr.id).first()
        assert audit is not None
        assert '1901' in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id

    def test_create_does_not_require_reason(self, client, db_session, two_reviewers):
        """Creating master data needs no reason — the reviewer judges the proposed data."""
        login(client)
        resp = client.post('/accounts/create',
                           data=account_form_data(reason=None),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert PENDING_FLASH in resp.data
        assert AccountChangeRequest.query.count() == 1

    def test_duplicate_pending_create_is_blocked(self, client, db_session, two_reviewers):
        login(client)
        client.post('/accounts/create', data=account_form_data(), follow_redirects=True)
        assert AccountChangeRequest.query.count() == 1

        resp = client.post('/accounts/create', data=account_form_data(),
                           follow_redirects=True)
        assert DUPLICATE_FLASH in resp.data
        assert AccountChangeRequest.query.count() == 1

    def test_duplicate_pending_update_is_blocked(self, client, db_session, two_reviewers):
        login(client)
        account = make_account(db_session)
        resp = client.post(f'/accounts/{account.id}/edit',
                           data=account_form_data(code=account.code, name='Renamed Account'),
                           follow_redirects=True)
        assert PENDING_FLASH in resp.data
        assert AccountChangeRequest.query.count() == 1

        resp = client.post(f'/accounts/{account.id}/edit',
                           data=account_form_data(code=account.code, name='Renamed Again'),
                           follow_redirects=True)
        assert DUPLICATE_FLASH in resp.data
        assert AccountChangeRequest.query.count() == 1

    def test_delete_requires_reason(self, client, db_session, two_reviewers):
        login(client)
        account = make_account(db_session)
        resp = client.post(f'/accounts/{account.id}/delete', data={},
                           follow_redirects=True)
        assert b'reason for the change is required' in resp.data
        assert AccountChangeRequest.query.count() == 0

    def test_delete_persists_reason_and_audit(self, client, db_session, two_reviewers):
        login(client)
        account = make_account(db_session)
        resp = client.post(f'/accounts/{account.id}/delete',
                           data={'request_reason': 'Account no longer used'},
                           follow_redirects=True)
        assert PENDING_FLASH in resp.data

        cr = AccountChangeRequest.query.one()
        assert cr.change_type == 'delete'
        assert cr.status == 'pending'
        assert cr.request_reason == 'Account no longer used'

        audit = AuditLog.query.filter_by(module='account', action='delete',
                                         record_id=cr.id).first()
        assert audit is not None
        assert account.code in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id

    def test_list_shows_pending_badge(self, client, db_session, two_reviewers):
        login(client)
        account = make_account(db_session)
        cr = AccountChangeRequest(
            change_type='update', account_id=account.id,
            change_data=json.dumps({'code': account.code, 'name': 'X'}),
            requested_by=two_reviewers[1].username, requested_at=ph_now(),
            status='pending', request_reason='test')
        db_session.add(cr)
        db_session.commit()

        resp = client.get('/accounts/')
        assert resp.status_code == 200
        assert b'Pending change' in resp.data

    def test_reject_writes_audit_with_reject_action(self, client, db_session, two_reviewers):
        # Request submitted by the accountant; admin rejects it
        login(client)
        account = make_account(db_session)
        cr = AccountChangeRequest(
            change_type='update', account_id=account.id,
            change_data=json.dumps({'code': account.code, 'name': 'Renamed',
                                    'account_type': 'Asset', 'normal_balance': 'debit'}),
            requested_by=two_reviewers[1].username, requested_at=ph_now(),
            status='pending', request_reason='test')
        db_session.add(cr)
        db_session.commit()

        resp = client.post(f'/accounts/reject/{cr.id}',
                           data={'rejection_reason': 'Not justified'},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert cr.status == 'rejected'
        assert cr.reviewed_by == two_reviewers[0].username

        audit = AuditLog.query.filter_by(module='account', action='reject',
                                         record_id=cr.id).first()
        assert audit is not None
        assert account.code in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id
        assert 'Not justified' in audit.notes

    def test_pending_approvals_page_shows_reason(self, client, db_session, two_reviewers):
        login(client)
        account = make_account(db_session)
        cr = AccountChangeRequest(
            change_type='update', account_id=account.id,
            change_data=json.dumps({'code': account.code, 'name': 'X',
                                    'account_type': 'Asset', 'normal_balance': 'debit'}),
            requested_by=two_reviewers[1].username, requested_at=ph_now(),
            status='pending', request_reason='Reclassification per auditor advice')
        db_session.add(cr)
        db_session.commit()

        resp = client.get('/accounts/pending-approvals')
        assert resp.status_code == 200
        assert b'Reclassification per auditor advice' in resp.data


# ───────────────────────── Dashboard Action Items ─────────────────────────

class TestActionItemsShowReason:
    def test_action_items_page_shows_reason_and_legacy_dash(self, client, db_session, two_reviewers):
        login(client)
        account = make_account(db_session)
        cr = AccountChangeRequest(
            change_type='update', account_id=account.id,
            change_data=json.dumps({'code': account.code, 'name': 'X'}),
            requested_by=two_reviewers[1].username, requested_at=ph_now(),
            status='pending', request_reason='Account restructure')
        db_session.add(cr)
        # Legacy row without a reason
        vat = make_vat(db_session)
        legacy = VATCategoryChangeRequest(
            action='update', status='pending', vat_category_id=vat.id,
            proposed_data=json.dumps({'code': vat.code, 'name': 'X', 'rate': 12.0}),
            requested_by_id=two_reviewers[1].id, requested_at=ph_now())
        db_session.add(legacy)
        db_session.commit()

        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert b'Account restructure' in resp.data
        # Legacy NULL reason renders as an em dash
        assert '—'.encode('utf-8') in resp.data


# ───────── Reason required on EDIT/DELETE but NOT on CREATE ─────────

class TestReasonRequiredOnEditNotCreate:
    """Master-data CREATE drops the 'Reason for Change' field; EDIT keeps it
    required (a genuine change the reviewer/audit trail must have justified)."""

    # --- EDIT still requires a reason ---

    def test_wht_edit_requires_reason(self, client, db_session, two_reviewers):
        login(client)
        wht = make_wht(db_session)
        resp = client.post(f'/withholding-tax/{wht.id}/edit',
                           data=wht_form_data(code=wht.code, name='Renamed WHT', reason=None),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert WithholdingTaxChangeRequest.query.count() == 0

    def test_vat_edit_requires_reason(self, client, db_session, two_reviewers):
        login(client)
        vat = make_vat(db_session)
        input_vat = make_input_vat_account(db_session)
        resp = client.post(f'/vat-categories/{vat.id}/edit',
                           data=vat_form_data(code=vat.code, name='Renamed VAT', reason=None,
                                              input_vat_account_id=input_vat.id),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert VATCategoryChangeRequest.query.count() == 0

    def test_account_edit_requires_reason(self, client, db_session, two_reviewers):
        login(client)
        account = make_account(db_session)
        resp = client.post(f'/accounts/{account.id}/edit',
                           data=account_form_data(code=account.code, name='Renamed Account',
                                                  reason=None),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert AccountChangeRequest.query.count() == 0

    # --- CREATE form omits the reason section; EDIT form shows it ---

    def test_wht_create_form_omits_reason_section(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/withholding-tax/create')
        assert resp.status_code == 200
        assert b'Reason for Change' not in resp.data

    def test_wht_edit_form_shows_reason_section(self, client, db_session, two_reviewers):
        login(client)
        wht = make_wht(db_session)
        resp = client.get(f'/withholding-tax/{wht.id}/edit')
        assert resp.status_code == 200
        assert b'Reason for Change' in resp.data

    def test_vat_create_form_omits_reason_section(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/vat-categories/create')
        assert resp.status_code == 200
        assert b'Reason for Change' not in resp.data

    def test_vat_edit_form_shows_reason_section(self, client, db_session, two_reviewers):
        login(client)
        vat = make_vat(db_session)
        resp = client.get(f'/vat-categories/{vat.id}/edit')
        assert resp.status_code == 200
        assert b'Reason for Change' in resp.data

    def test_account_create_form_omits_reason_section(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/accounts/create')
        assert resp.status_code == 200
        assert b'Reason for Change' not in resp.data

    def test_account_edit_form_shows_reason_section(self, client, db_session, two_reviewers):
        login(client)
        account = make_account(db_session)
        resp = client.get(f'/accounts/{account.id}/edit')
        assert resp.status_code == 200
        assert b'Reason for Change' in resp.data


# ───── Approval-time uniqueness re-check (TOCTOU on create) ─────

class TestApprovalUniquenessRecheck:
    """A pending create request whose code/name has since been taken (by another
    approved request or a direct create) must NOT be approved into a duplicate —
    block with a clean message and leave the request pending."""

    # --- Withholding Tax ---

    def test_wht_approve_create_blocked_when_code_taken(self, client, db_session, two_reviewers):
        login(client)
        client.post('/withholding-tax/create',
                    data=wht_form_data(code='WCX', name='New WHT'), follow_redirects=True)
        cr = WithholdingTaxChangeRequest.query.one()
        make_wht(db_session, code='WCX', name='Pre-existing')   # code now taken
        # Switch to admin2 (second reviewer) so self-approval guard doesn't fire
        client.get('/logout', follow_redirects=True)  # must log out before switching users
        login(client, username='admin2', password='admin2pass')
        resp = client.post(f'/withholding-tax/change-requests/{cr.id}/review',
                           data={'action': 'approve', 'review_notes': ''}, follow_redirects=True)
        assert 'already exists' in html.unescape(resp.data.decode())
        assert WithholdingTax.query.filter_by(code='WCX').count() == 1
        db_session.refresh(cr)
        assert cr.status == 'pending'

    def test_wht_approve_create_blocked_when_name_taken(self, client, db_session, two_reviewers):
        login(client)
        client.post('/withholding-tax/create',
                    data=wht_form_data(code='WCY', name='Dup Name'), follow_redirects=True)
        cr = WithholdingTaxChangeRequest.query.one()
        make_wht(db_session, code='WCZ', name='Dup Name')       # name now taken (diff code)
        client.get('/logout', follow_redirects=True)  # must log out before switching users
        login(client, username='admin2', password='admin2pass')
        resp = client.post(f'/withholding-tax/change-requests/{cr.id}/review',
                           data={'action': 'approve', 'review_notes': ''}, follow_redirects=True)
        assert 'already exists' in html.unescape(resp.data.decode())
        assert WithholdingTax.query.filter_by(name='Dup Name').count() == 1
        db_session.refresh(cr)
        assert cr.status == 'pending'

    # --- VAT Categories ---

    def test_vat_approve_create_blocked_when_code_taken(self, client, db_session, two_reviewers):
        login(client)
        input_vat = make_input_vat_account(db_session)
        client.post('/vat-categories/create',
                    data=vat_form_data(code='VATX', name='New VAT', input_vat_account_id=input_vat.id),
                    follow_redirects=True)
        cr = VATCategoryChangeRequest.query.one()
        make_vat(db_session, code='VATX', name='Pre-existing')
        client.get('/logout', follow_redirects=True)  # must log out before switching users
        login(client, username='admin2', password='admin2pass')
        resp = client.post(f'/vat-categories/change-requests/{cr.id}/review',
                           data={'action': 'approve', 'review_notes': ''}, follow_redirects=True)
        assert 'already exists' in html.unescape(resp.data.decode())
        assert VATCategory.query.filter_by(code='VATX').count() == 1
        db_session.refresh(cr)
        assert cr.status == 'pending'

    def test_vat_approve_create_blocked_when_name_taken(self, client, db_session, two_reviewers):
        login(client)
        input_vat = make_input_vat_account(db_session)
        client.post('/vat-categories/create',
                    data=vat_form_data(code='VATY', name='Dup VAT', input_vat_account_id=input_vat.id),
                    follow_redirects=True)
        cr = VATCategoryChangeRequest.query.one()
        make_vat(db_session, code='VATZ', name='Dup VAT')
        client.get('/logout', follow_redirects=True)  # must log out before switching users
        login(client, username='admin2', password='admin2pass')
        resp = client.post(f'/vat-categories/change-requests/{cr.id}/review',
                           data={'action': 'approve', 'review_notes': ''}, follow_redirects=True)
        assert 'already exists' in html.unescape(resp.data.decode())
        assert VATCategory.query.filter_by(name='Dup VAT').count() == 1
        db_session.refresh(cr)
        assert cr.status == 'pending'

    # --- Chart of Accounts ---

    def test_account_approve_create_blocked_when_code_taken(self, client, db_session, two_reviewers):
        login(client)
        client.post('/accounts/create',
                    data=account_form_data(code='1901', name='New Acct'), follow_redirects=True)
        cr = AccountChangeRequest.query.one()
        make_account(db_session, code='1901', name='Pre-existing Acct')
        resp = client.post(f'/accounts/approve/{cr.id}', data={}, follow_redirects=True)
        assert 'already exists' in html.unescape(resp.data.decode())
        assert Account.query.filter_by(code='1901').count() == 1
        db_session.refresh(cr)
        assert cr.status == 'pending'

    def test_account_approve_create_blocked_when_name_taken(self, client, db_session, two_reviewers):
        login(client)
        client.post('/accounts/create',
                    data=account_form_data(code='1902', name='Dup Acct'), follow_redirects=True)
        cr = AccountChangeRequest.query.one()
        make_account(db_session, code='1903', name='Dup Acct')
        resp = client.post(f'/accounts/approve/{cr.id}', data={}, follow_redirects=True)
        assert 'already exists' in html.unescape(resp.data.decode())
        assert Account.query.filter_by(name='Dup Acct').count() == 1
        db_session.refresh(cr)
        assert cr.status == 'pending'


# ───────── Required-field markers on the create forms ─────────

class TestRequiredFieldMarkers:
    """Required fields on the master-data create forms carry a visual marker
    (the shared `.required` asterisk)."""

    def test_wht_create_form_marks_required_fields(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/withholding-tax/create')
        assert resp.status_code == 200
        assert b'class="required"' in resp.data

    def test_vat_create_form_marks_required_fields(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/vat-categories/create')
        assert resp.status_code == 200
        assert b'class="required"' in resp.data

    def test_account_create_form_marks_required_fields(self, client, db_session, two_reviewers):
        login(client)
        resp = client.get('/accounts/create')
        assert resp.status_code == 200
        assert b'class="required"' in resp.data

