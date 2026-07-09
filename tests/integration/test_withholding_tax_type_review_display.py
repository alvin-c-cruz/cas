"""Reviewer visibility of the proposed BIR withholding regime (tax_type).

Important-finding fix: review_change_request.html and change_requests.html
hardcoded an explicit field list (code/name/sales_name/description/rate/
is_active/payable_account_id/receivable_account_id) that omitted tax_type,
so an approver reviewing a create or update Withholding Tax change request
saw no signal of the proposed expanded/final regime. Approving a final-tax
code as expanded would put non-creditable tax onto a 2307 and a SAWT.

Asserts the human-readable label (from app.withholding_tax.models.
TAX_TYPE_LABELS) is actually present in the rendered review + list pages --
not just the raw token -- for both a pending 'create' request and a pending
'update' request (old -> new diff).
"""
import json

import pytest

from app.withholding_tax.models import WithholdingTax, WithholdingTaxChangeRequest, TAX_TYPE_LABELS

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    # Logout first: the login view redirects already-authenticated users,
    # so switching users mid-test requires clearing the session.
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_second_admin(db_session):
    from app.users.models import User
    second_admin = User(username='admin2', email='admin2@example.com',
                        full_name='Second Admin', role='admin', is_active=True)
    second_admin.set_password('admin2pass')
    db_session.add(second_admin)
    db_session.commit()
    return second_admin


def wht_data(code='WTX', name='Test WHT', tax_type='final'):
    return {
        'code': code, 'name': name, 'sales_name': '', 'description': 'test',
        'rate': '20.00', 'tax_type': tax_type, 'is_active': '1',
        'payable_account_id': '0', 'receivable_account_id': '0',
        'request_reason': 'tax_type review-display test',
    }


class TestTaxTypeShownOnReview:
    def test_create_request_review_page_shows_proposed_regime_label(
            self, client, db_session, admin_user, main_branch):
        """Two full-access users => the create goes to 'pending'. The second
        admin's review page must show the human-readable label for the
        proposed tax_type ('final' -> 'Final'), not just the raw token."""
        make_second_admin(db_session)

        login(client, 'admin', 'admin123')
        client.post('/withholding-tax/create',
                    data=wht_data(code='WTF', tax_type='final'),
                    follow_redirects=True)

        req = WithholdingTaxChangeRequest.query.order_by(
            WithholdingTaxChangeRequest.id.desc()).first()
        assert req is not None
        assert req.status == 'pending'
        assert json.loads(req.proposed_data)['tax_type'] == 'final'

        login(client, 'admin2', 'admin2pass')
        resp = client.get(f'/withholding-tax/change-requests/{req.id}/review')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert TAX_TYPE_LABELS['final'] in body

        resp = client.get('/withholding-tax/change-requests')
        assert resp.status_code == 200
        assert TAX_TYPE_LABELS['final'] in resp.data.decode()

    def test_update_request_review_page_shows_old_and_new_regime_labels(
            self, client, db_session, admin_user, main_branch):
        """An update proposing a DIFFERENT regime than the code's current one
        must show BOTH the current label and the proposed label, so an
        approver sees the old -> new regime diff (mirrors how rate/status
        diffs are already shown)."""
        make_second_admin(db_session)

        wht = WithholdingTax(code='WTU', name='Upd Regime', rate=10.00,
                             is_active=True, tax_type='expanded')
        db_session.add(wht)
        db_session.commit()

        login(client, 'admin', 'admin123')
        data = wht_data(code='WTU', name='Upd Regime', tax_type='final')
        client.post(f'/withholding-tax/{wht.id}/edit', data=data,
                    follow_redirects=True)

        req = WithholdingTaxChangeRequest.query.order_by(
            WithholdingTaxChangeRequest.id.desc()).first()
        assert req is not None
        assert req.status == 'pending'
        assert json.loads(req.proposed_data)['tax_type'] == 'final'

        login(client, 'admin2', 'admin2pass')
        resp = client.get(f'/withholding-tax/change-requests/{req.id}/review')
        assert resp.status_code == 200
        body = resp.data.decode()
        # An approver must see BOTH the current regime and the proposed one --
        # a blind approval that shows only one side would not catch a
        # submitter approving a final-tax code as expanded (or vice versa).
        assert TAX_TYPE_LABELS['expanded'] in body
        assert TAX_TYPE_LABELS['final'] in body
