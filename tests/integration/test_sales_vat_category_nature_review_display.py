"""Reviewer visibility of the proposed BIR transaction_nature classification
-- sales-side twin of test_vat_category_nature_review_display.py.

BUG-SALES-VAT-NATURE-RAW-VALUE: review_change_request.html rendered the bare
DB token (e.g. 'domestic_services'... actually 'regular') for both the
create/update diff view and the delete view, instead of the human-readable
label (app.sales_vat_categories.models.SALES_NATURE_LABELS). Asserts the
label is actually present in the rendered review page for a pending create
and a pending delete request.
"""
import json

from app.sales_vat_categories.models import (
    SalesVATCategory, SalesVATCategoryChangeRequest, SALES_NATURE_LABELS)
from app.accounts.models import Account
import pytest

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_account(db_session, code='2310', name='Output Tax Payable'):
    a = Account(code=code, name=name, account_type='Liability',
                normal_balance='Credit', is_active=True)
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


def sales_vat_data(account_id, code='V12T', nature='zero_export'):
    return {
        'code': code, 'name': f'Test {code}', 'description': 'test',
        'rate': '12.00', 'is_active': '1',
        'output_vat_account_id': str(account_id),
        'transaction_nature': nature,
        'request_reason': 'sales nature review-display test',
    }


class TestSalesNatureShownOnReview:
    def test_create_request_review_page_shows_proposed_nature_label(
            self, client, db_session, admin_user, main_branch):
        """Two full-access users => the create goes to 'pending'. The second
        admin's review page must show the human-readable label for the
        proposed transaction_nature ('zero_export' -> 'Zero-Rated (Export)'),
        not just the raw token."""
        make_second_admin(db_session)
        acct = make_account(db_session)

        login(client, 'admin', 'admin123')
        client.post('/sales-vat-categories/create',
                    data=sales_vat_data(acct.id, code='V12N', nature='zero_export'),
                    follow_redirects=True)

        req = SalesVATCategoryChangeRequest.query.order_by(
            SalesVATCategoryChangeRequest.id.desc()).first()
        assert req is not None
        assert req.status == 'pending'
        assert json.loads(req.proposed_data)['transaction_nature'] == 'zero_export'

        login(client, 'admin2', 'admin2pass')
        resp = client.get(f'/sales-vat-categories/change-requests/{req.id}/review')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert SALES_NATURE_LABELS['zero_export'] in body
        assert '>zero_export<' not in body

    def test_delete_request_review_page_shows_nature_label(
            self, client, db_session, admin_user, main_branch):
        """review_change_request.html's delete branch must also show the
        friendly label, not just code/name/description/rate."""
        make_second_admin(db_session)
        acct = make_account(db_session)

        cat = SalesVATCategory(code='V12D', name='Del Nature', rate=12.00, is_active=True,
                               output_vat_account_id=acct.id,
                               transaction_nature='government')
        db_session.add(cat)
        db_session.commit()

        login(client, 'admin', 'admin123')
        client.post(f'/sales-vat-categories/{cat.id}/delete',
                    data={'request_reason': 'sales nature review-display delete test'},
                    follow_redirects=True)

        req = SalesVATCategoryChangeRequest.query.order_by(
            SalesVATCategoryChangeRequest.id.desc()).first()
        assert req is not None
        assert req.status == 'pending'
        assert req.action == 'delete'

        login(client, 'admin2', 'admin2pass')
        resp = client.get(f'/sales-vat-categories/change-requests/{req.id}/review')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert SALES_NATURE_LABELS['government'] in body
        assert '>government<' not in body
