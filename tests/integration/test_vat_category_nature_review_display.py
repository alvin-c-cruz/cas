"""Reviewer visibility of the proposed BIR transaction_nature classification.

Important-finding fix: review_change_request.html and change_requests.html
hardcoded an explicit field list (code/name/description/rate/is_active/
input_vat_account) that omitted transaction_nature, so an approver reviewing
a create or update change request saw no signal of the proposed BIR 2550Q
Part II classification. This asserts the human-readable label (from
app.vat_categories.forms._NATURE_LABELS) is actually present in the
rendered review + list pages -- not just the raw enum token -- for both a
pending 'create' request and a pending 'update' request (old -> new diff).
"""
import json

from app.vat_categories.forms import _NATURE_LABELS
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
from app.accounts.models import Account
import pytest

pytestmark = [pytest.mark.vat_categories, pytest.mark.integration]


def login(client, username, password):
    # Logout first: the login view redirects already-authenticated users,
    # so switching users mid-test requires clearing the session.
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_account(db_session, code='10502', name='Input VAT - Domestic Goods'):
    a = Account(code=code, name=name, account_type='Asset',
                normal_balance='Debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


def make_second_admin(db_session):
    from app.users.models import User
    second_admin = User(username='admin2', email='admin2@example.com',
                        full_name='Second Admin', role='admin', is_active=True)
    second_admin.set_password('admin2pass')
    db_session.add(second_admin)
    db_session.commit()
    return second_admin


def vat_data(account_id, code='V12T', nature='domestic_services'):
    return {
        'code': code, 'name': f'Test {code}', 'description': 'test',
        'rate': '12.00', 'is_active': '1',
        'input_vat_account_id': str(account_id),
        'transaction_nature': nature,
        'request_reason': 'nature review-display test',
    }


class TestNatureShownOnReview:
    def test_create_request_review_page_shows_proposed_nature_label(
            self, client, db_session, admin_user, accountant_user, main_branch):
        """Two full-access users => the create goes to 'pending'. The second
        admin's review page must show the human-readable label for the
        proposed transaction_nature ('capital_goods' -> 'Capital Goods'),
        not just the raw token."""
        make_second_admin(db_session)
        acct = make_account(db_session)

        login(client, 'admin', 'admin123')
        client.post('/vat-categories/create',
                    data=vat_data(acct.id, code='V12N', nature='capital_goods'),
                    follow_redirects=True)

        req = VATCategoryChangeRequest.query.order_by(
            VATCategoryChangeRequest.id.desc()).first()
        assert req is not None
        assert req.status == 'pending'
        assert json.loads(req.proposed_data)['transaction_nature'] == 'capital_goods'

        login(client, 'admin2', 'admin2pass')
        resp = client.get(f'/vat-categories/change-requests/{req.id}/review')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert _NATURE_LABELS['capital_goods'] in body

        resp = client.get('/vat-categories/change-requests')
        assert resp.status_code == 200
        assert _NATURE_LABELS['capital_goods'] in resp.data.decode()

    def test_update_request_review_page_shows_old_and_new_nature_labels(
            self, client, db_session, admin_user, accountant_user, main_branch):
        """An update proposing a DIFFERENT nature than the category's current
        one must show BOTH the current label and the proposed label, so an
        approver sees the old -> new classification diff (mirrors how
        rate/status/input_vat_account diffs are already shown)."""
        make_second_admin(db_session)
        a1 = make_account(db_session, code='10501', name='Input VAT - Capital Goods')

        cat = VATCategory(code='V12U', name='Upd Nature', rate=12.00, is_active=True,
                          input_vat_account_id=a1.id,
                          transaction_nature='domestic_goods')
        db_session.add(cat)
        db_session.commit()

        login(client, 'admin', 'admin123')
        data = vat_data(a1.id, code='V12U', nature='domestic_services')
        data['name'] = 'Upd Nature'
        client.post(f'/vat-categories/{cat.id}/edit', data=data,
                    follow_redirects=True)

        req = VATCategoryChangeRequest.query.order_by(
            VATCategoryChangeRequest.id.desc()).first()
        assert req is not None
        assert req.status == 'pending'
        assert json.loads(req.proposed_data)['transaction_nature'] == 'domestic_services'

        login(client, 'admin2', 'admin2pass')
        resp = client.get(f'/vat-categories/change-requests/{req.id}/review')
        assert resp.status_code == 200
        body = resp.data.decode()
        # An approver must see BOTH the current classification and the
        # proposed one -- a blind approval that shows only one side would
        # not catch a submitter mis-selecting the wrong BIR box.
        assert _NATURE_LABELS['domestic_goods'] in body
        assert _NATURE_LABELS['domestic_services'] in body
