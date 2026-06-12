"""Integration tests for the master-data change-request workflow (B-006).

Covers Chart of Accounts, VAT Categories and Withholding Tax:
- "Reason for change" is required and persisted on the change request
- Duplicate pending requests for the same record are blocked
- Submission feedback flash is shown
- Audit entries are written with the correct action, record reference and actor
"""
import json

import pytest

from app.accounts.models import Account
from app.accounts.approval_models import AccountChangeRequest
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
from app.withholding_tax.models import WithholdingTax, WithholdingTaxChangeRequest
from app.audit.models import AuditLog
from app.utils import ph_now


PENDING_FLASH = b'Change request submitted'
DUPLICATE_FLASH = b'A pending change request for this record already exists'


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def two_reviewers(admin_user, accountant_user, main_branch):
    """Two active accountant/admin users so can_auto_approve() is False.

    A branch must exist for login to succeed.
    """
    return admin_user, accountant_user


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
        assert cr.request_reason == 'New VAT type required'

        audit = AuditLog.query.filter_by(module='vat_category', action='create',
                                         record_id=cr.id).first()
        assert audit is not None
        assert 'VATX' in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id
        assert 'New VAT type required' in audit.notes

    def test_create_reason_is_required(self, client, db_session, two_reviewers):
        login(client)
        input_vat = make_input_vat_account(db_session)
        resp = client.post('/vat-categories/create',
                           data=vat_form_data(reason=None,
                                              input_vat_account_id=input_vat.id),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert VATCategoryChangeRequest.query.count() == 0

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
        assert cr.request_reason == 'New WHT code required'

        audit = AuditLog.query.filter_by(module='withholding_tax', action='create',
                                         record_id=cr.id).first()
        assert audit is not None
        assert 'WCX' in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id
        assert 'New WHT code required' in audit.notes

    def test_create_reason_is_required(self, client, db_session, two_reviewers):
        login(client)
        resp = client.post('/withholding-tax/create',
                           data=wht_form_data(reason=None),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert WithholdingTaxChangeRequest.query.count() == 0

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
        assert cr.request_reason == 'Adding petty cash account'

        audit = AuditLog.query.filter_by(module='account', action='create',
                                         record_id=cr.id).first()
        assert audit is not None
        assert '1901' in audit.record_identifier
        assert audit.user_id == two_reviewers[0].id
        assert 'Adding petty cash account' in audit.notes

    def test_create_reason_is_required(self, client, db_session, two_reviewers):
        login(client)
        resp = client.post('/accounts/create',
                           data=account_form_data(reason=None),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert AccountChangeRequest.query.count() == 0

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
