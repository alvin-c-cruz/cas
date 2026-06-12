"""Input-tax account flows through the VAT change-request workflow (B-014)."""
import json

from app.accounts.models import Account
from app.audit.models import AuditLog
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest


def login(client, username, password):
    # Login view redirects authenticated users, so log out before switching.
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_account(db_session, code='10502', name='Input VAT - Domestic Goods'):
    a = Account(code=code, name=name, account_type='Asset',
                normal_balance='Debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


def vat_data(account_id, code='V12T', rate='12.00'):
    return {
        'code': code, 'name': f'Test {code}', 'description': 'test',
        'rate': rate, 'is_active': '1',
        'input_vat_account_id': str(account_id),
        'request_reason': 'B-014 workflow test',
    }


class TestInputAccountWorkflow:
    def test_admin_create_pending_then_approved_applies_account(
            self, client, db_session, admin_user, accountant_user, main_branch):
        acct = make_account(db_session)
        login(client, 'admin', 'admin123')
        client.post('/vat-categories/create', data=vat_data(acct.id),
                    follow_redirects=True)

        req = VATCategoryChangeRequest.query.order_by(
            VATCategoryChangeRequest.id.desc()).first()
        assert req is not None
        assert req.status == 'pending'
        assert json.loads(req.proposed_data)['input_vat_account_id'] == acct.id

        login(client, 'accountant', 'accountant123')
        client.post(f'/vat-categories/change-requests/{req.id}/review',
                    data={'action': 'approve', 'review_notes': 'ok'},
                    follow_redirects=True)

        cat = VATCategory.query.filter_by(code='V12T').first()
        assert cat is not None
        assert cat.input_vat_account_id == acct.id

        audit = AuditLog.query.filter_by(module='vat_category', action='create',
                                         record_id=cat.id).first()
        assert audit is not None

    def test_sole_accountant_autoapprove_sets_account(
            self, client, db_session, admin_user, accountant_user, main_branch):
        acct = make_account(db_session, code='10503', name='Input VAT - Services')
        login(client, 'accountant', 'accountant123')
        client.post('/vat-categories/create', data=vat_data(acct.id, code='V12S'),
                    follow_redirects=True)
        cat = VATCategory.query.filter_by(code='V12S').first()
        assert cat is not None
        assert cat.input_vat_account_id == acct.id

    def test_update_changes_account_through_workflow(
            self, client, db_session, admin_user, accountant_user, main_branch):
        a1 = make_account(db_session, code='10501', name='Input VAT - Capital Goods')
        a2 = make_account(db_session, code='10502', name='Input VAT - Domestic Goods')
        cat = VATCategory(code='V12U', name='Upd 12%', rate=12.00, is_active=True,
                          input_vat_account_id=a1.id)
        db_session.add(cat)
        db_session.commit()

        login(client, 'admin', 'admin123')
        data = vat_data(a2.id, code='V12U')
        data['name'] = 'Upd 12%'
        client.post(f'/vat-categories/{cat.id}/edit', data=data,
                    follow_redirects=True)
        req = VATCategoryChangeRequest.query.order_by(
            VATCategoryChangeRequest.id.desc()).first()
        assert req is not None
        assert req.status == 'pending'

        login(client, 'accountant', 'accountant123')
        client.post(f'/vat-categories/change-requests/{req.id}/review',
                    data={'action': 'approve', 'review_notes': 'ok'},
                    follow_redirects=True)
        assert db_session.get(VATCategory, cat.id).input_vat_account_id == a2.id
