"""VAT 2.6 B: a sole full-access user may review and apply their OWN tax-master change request, with a reason.

Owner, 14 Nov 2026: "VAT 2.6 B" -- "A sole admin may apply a rate change themselves, with a reason that goes into the
audit log. The two-person rule still applies wherever a second reviewer exists." Work order
2026-07-12-vat-rate-change-stuck-no-reviewer.md; memory `tax-rate-edit-review-gate` (amended).

Before: on a book with one Administrator and no Chief Accountant, a rate change sat pending forever. The review
route already let a lone reviewer through, but change_requests.html offered only Withdraw on your own request, so
no screen led there. "Sole" is the app's existing test, sole_full_access_user_can_auto_approve() -- the requester
is full access and the only active admin/chief accountant.

Same tests in all three modules (VAT categories, sales VAT categories, withholding tax).
"""
from decimal import Decimal

import pytest
from flask import url_for

from app.audit.models import AuditLog
from tests.integration.test_taxmaster_withdraw_pending import (_svat_pending_cr, _vat_pending_cr,
                                                                _wht_pending_cr, login)

pytestmark = [pytest.mark.integration]

REASON = 'BIR RR 3-2026 changes the rate from 1 Dec'

MODULES = [
    pytest.param('vat_categories', 'vat_category', lambda s, uid, acct: _vat_pending_cr(
        s, uid, old_rate='12.00', new_rate='10.00', account_id=acct), Decimal('10.00'), id='vat'),
    pytest.param('sales_vat_categories', 'sales_vat_category', lambda s, uid, acct: _svat_pending_cr(
        s, uid, old_rate='12.00', new_rate='10.00', account_id=acct), Decimal('10.00'), id='sales_vat'),
    pytest.param('withholding_tax', 'withholding_tax', lambda s, uid, acct: _wht_pending_cr(
        s, uid, old_rate='10.00', new_rate='2.00'), Decimal('2.00'), id='wht'),
]


def _setup(db_session, admin_user, main_branch, cash_account, build):
    admin_user.add_branch(main_branch)
    db_session.commit()
    return build(db_session, admin_user.id, cash_account.id)


@pytest.mark.parametrize('bp,audit_module,build,new_rate', MODULES)
class TestSoleReviewer:

    def test_the_list_offers_review_and_explains_why(self, client, db_session, admin_user, main_branch,
                                                      cash_account, bp, audit_module, build, new_rate):
        rec, cr = _setup(db_session, admin_user, main_branch, cash_account, build)
        login(client, 'admin', 'admin123')
        html = client.get(url_for(f'{bp}.change_requests')).data.decode('utf-8')
        assert url_for(f'{bp}.review_change_request', id=cr.id) in html
        assert url_for(f'{bp}.withdraw_change_request', id=cr.id) in html, 'withdraw stays'
        assert 'No other Administrator or Chief Accountant' in html

    def test_applying_your_own_needs_a_reason(self, client, db_session, admin_user, main_branch,
                                              cash_account, bp, audit_module, build, new_rate):
        rec, cr = _setup(db_session, admin_user, main_branch, cash_account, build)
        old = rec.rate
        login(client, 'admin', 'admin123')
        client.post(url_for(f'{bp}.review_change_request', id=cr.id),
                    data={'action': 'approve', 'review_notes': '   '}, follow_redirects=True)
        db_session.refresh(rec)
        db_session.refresh(cr)
        assert rec.rate == old and cr.status == 'pending'

    def test_with_a_reason_it_applies_and_the_reason_is_audited(
            self, client, db_session, admin_user, main_branch, cash_account, bp, audit_module, build, new_rate):
        rec, cr = _setup(db_session, admin_user, main_branch, cash_account, build)
        login(client, 'admin', 'admin123')
        page = client.get(url_for(f'{bp}.review_change_request', id=cr.id))
        assert page.status_code == 200 and b'recorded in the audit log' in page.data
        client.post(url_for(f'{bp}.review_change_request', id=cr.id),
                    data={'action': 'approve', 'review_notes': REASON}, follow_redirects=True)
        db_session.refresh(rec)
        db_session.refresh(cr)
        assert rec.rate == new_rate and cr.status == 'approved'
        row = (AuditLog.query.filter_by(module=audit_module, action='update', record_id=rec.id)
               .order_by(AuditLog.id.desc()).first())
        assert row is not None
        assert REASON in row.notes and 'own request' in row.notes

    def test_with_a_second_reviewer_the_two_person_rule_holds(
            self, client, db_session, admin_user, chief_accountant_user, main_branch, cash_account,
            bp, audit_module, build, new_rate):
        rec, cr = _setup(db_session, admin_user, main_branch, cash_account, build)
        old = rec.rate
        login(client, 'admin', 'admin123')
        html = client.get(url_for(f'{bp}.change_requests')).data.decode('utf-8')
        assert url_for(f'{bp}.review_change_request', id=cr.id) not in html
        assert 'No other Administrator or Chief Accountant' not in html
        client.post(url_for(f'{bp}.review_change_request', id=cr.id),
                    data={'action': 'approve', 'review_notes': REASON}, follow_redirects=True)
        db_session.refresh(rec)
        db_session.refresh(cr)
        assert rec.rate == old and cr.status == 'pending'

    def test_another_reviewers_approval_is_audited_as_before(
            self, client, db_session, admin_user, chief_accountant_user, main_branch, cash_account,
            bp, audit_module, build, new_rate):
        rec, cr = _setup(db_session, admin_user, main_branch, cash_account, build)
        chief_accountant_user.set_password('chief12345!A')
        db_session.commit()
        login(client, chief_accountant_user.username, 'chief12345!A')
        client.post(url_for(f'{bp}.review_change_request', id=cr.id),
                    data={'action': 'approve', 'review_notes': REASON}, follow_redirects=True)
        db_session.refresh(rec)
        assert rec.rate == new_rate
        row = (AuditLog.query.filter_by(module=audit_module, action='update', record_id=rec.id)
               .order_by(AuditLog.id.desc()).first())
        assert 'own request' not in row.notes
