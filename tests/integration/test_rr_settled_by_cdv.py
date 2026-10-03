"""A receiving report can be settled by the cash voucher that paid it, outside AP.

Owner, 2026-10-03: the AP module started in September, so a receipt paid in August by a
legacy cash voucher can never be billed -- it would sit 'approved, unbilled' for good and
show in every unbilled-receipt check. The administrator (only -- "is B accessible for
users?") may close such a receipt against a POSTED CDV paid to the same vendor. The receipt
becomes 'billed' with `settled_cdv_id` naming the voucher; cancelling that voucher reopens it.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.audit.models import AuditLog
from app.cash_disbursements.models import CashDisbursementVoucher
from app.purchase_billing import billable_rrs_for
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from app.vendors.models import Vendor
from tests.integration.test_receiving_reports_lifecycle import (_approved_po, _login,  # noqa: F401
                                                                rr_enabled)

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]

REASON = 'August receipt paid by legacy CV 1613 before the AP module'


def _approved_rr(db_session, branch, vendor, number='00684', status='approved'):
    po = _approved_po(db_session, branch, vendor, qty=5, number='PO-' + number)
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 29),
                         vendor_id=vendor.id, vendor_name=vendor.name, status=status)
    rr.line_items.append(ReceivingReportItem(line_number=1,
                                             purchase_order_item_id=po.line_items[0].id,
                                             received_quantity=Decimal('5')))
    db_session.add(rr)
    db_session.commit()
    return rr


def _cdv(db_session, branch, vendor, cash_account, number='1613', status='posted'):
    cdv = CashDisbursementVoucher(branch_id=branch.id, cdv_number=number,
                                  cdv_date=date(2026, 8, 10), payee_type='vendor',
                                  payee_id=vendor.id, vendor_id=vendor.id,
                                  vendor_name=vendor.name, cash_account_id=cash_account.id,
                                  status=status)
    db_session.add(cdv)
    db_session.commit()
    return cdv


def _settle(client, rr, number='1613', reason=REASON):
    return client.post(f'/receiving-reports/{rr.id}/settle',
                       data={'cdv_number': number, 'settle_reason': reason},
                       follow_redirects=True)


def _as(client, user, branch, db_session):
    """Log *user* in on *branch*. A non-admin needs the branch and the Receiving Reports
    module granted -- as the real receiving clerk has -- or the request is turned away
    before it ever reaches the route under test, and a refusal test would pass vacuously."""
    if not user.has_full_access:
        import json
        perms = json.loads(user.book_permissions or '{}')
        perms['receiving_reports'] = True
        user.set_book_permissions(perms)
        user.set_branches([branch])
        db_session.commit()
    _switch_user(client, user, branch)


def _switch_user(client, user, branch):
    """Log *user* in. The test app context outlives each request, so Flask-Login's
    per-context user cache (g._login_user) would otherwise keep serving whoever made the
    first request of the test -- the second user would silently act as the first."""
    from flask import g
    g.pop('_login_user', None)
    _login(client, user, branch)


def _other_vendor(db_session):
    v = Vendor(code='OTH01', name='Other Vendor Inc.', check_payee_name='Other Vendor Inc.',
               is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


# ------------------------------------------------------------------- settling

class TestSettling:

    def test_the_administrator_settles_an_approved_receipt(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        cdv = _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)

        resp = _settle(client, rr)

        db_session.refresh(rr)
        assert rr.status == 'billed'
        assert rr.settled_cdv_id == cdv.id
        assert rr.settled_by_id == admin_user.id
        assert rr.settled_at is not None
        assert rr.settle_reason == REASON
        assert rr.accounts_payable_id is None, 'no AP voucher is invented'
        assert b'settled by CDV 1613' in resp.data

    def test_a_settled_receipt_is_no_longer_offered_for_billing(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)
        assert rr.id in [r['id'] for r in billable_rrs_for(main_branch.id, vl_vendor.id)]

        _settle(client, rr)

        assert rr.id not in [r['id'] for r in billable_rrs_for(main_branch.id, vl_vendor.id)]

    def test_settling_writes_a_real_audit_diff(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)

        _settle(client, rr)

        row = (AuditLog.query.filter_by(module='receiving_reports', action='settle',
                                        record_id=rr.id).order_by(AuditLog.id.desc()).first())
        assert row is not None
        old = row.old_values if isinstance(row.old_values, dict) else __import__('json').loads(row.old_values)
        new = row.new_values if isinstance(row.new_values, dict) else __import__('json').loads(row.new_values)
        assert (old['status'], old['settled_cdv']) == ('approved', None)
        assert (new['status'], new['settled_cdv']) == ('billed', '1613')
        assert 'CDV 1613' in (row.notes or '')

    def test_a_cdv_of_another_branch_may_settle_it(
            self, client, admin_user, main_branch, branch_manila, vl_vendor, cash_account,
            db_session):
        """Purchasing lives in CORP; the payment comes from whichever branch pays."""
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, branch_manila, vl_vendor, cash_account, number='1613E')
        _login(client, admin_user, main_branch)

        _settle(client, rr, number='1613E')

        db_session.refresh(rr)
        assert rr.status == 'billed'


# ------------------------------------------------------------------- refusals

class TestRefusals:

    @pytest.mark.parametrize('who', ['staff_user', 'accountant_user'])
    def test_only_the_administrator_may_settle(
            self, request, client, main_branch, vl_vendor, cash_account, db_session, who):
        user = request.getfixturevalue(who)
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _as(client, user, main_branch, db_session)

        resp = _settle(client, rr)

        db_session.refresh(rr)
        assert (rr.status, rr.settled_cdv_id) == ('approved', None)
        assert b'Only the administrator' in resp.data

    @pytest.mark.parametrize('status', ['draft', 'voided', 'cancelled'])
    def test_only_a_posted_cdv_settles(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session, status):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account, status=status)
        _login(client, admin_user, main_branch)

        resp = _settle(client, rr)

        db_session.refresh(rr)
        assert (rr.status, rr.settled_cdv_id) == ('approved', None)
        assert b'only a posted CDV' in resp.data

    def test_another_vendors_cdv_is_refused(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, _other_vendor(db_session), cash_account)
        _login(client, admin_user, main_branch)

        resp = _settle(client, rr)

        db_session.refresh(rr)
        assert rr.settled_cdv_id is None
        assert b'paid Other Vendor Inc.' in resp.data

    def test_an_unknown_cdv_number_is_refused(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _login(client, admin_user, main_branch)

        resp = _settle(client, rr, number='9999')

        db_session.refresh(rr)
        assert rr.settled_cdv_id is None
        assert b'No Cash Disbursement Voucher has that number' in resp.data

    def test_a_short_reason_is_refused(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)

        resp = _settle(client, rr, reason='paid')

        db_session.refresh(rr)
        assert rr.settled_cdv_id is None
        assert b'at least 10 characters' in resp.data

    @pytest.mark.parametrize('status', ['draft', 'submitted', 'cancelled'])
    def test_a_receipt_that_is_not_approved_is_refused(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session, status):
        rr = _approved_rr(db_session, main_branch, vl_vendor, status=status)
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)

        _settle(client, rr)

        db_session.refresh(rr)
        assert (rr.status, rr.settled_cdv_id) == (status, None)

    def test_a_receipt_billed_by_an_ap_voucher_is_refused(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        from tests.integration.test_rr_against_billed_first_po import _bill
        ap = _bill(db_session, main_branch, vl_vendor, 'AP-SET-1')
        rr = _approved_rr(db_session, main_branch, vl_vendor, status='billed')
        rr.accounts_payable_id = ap.id
        db_session.commit()
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)

        resp = _settle(client, rr)

        db_session.refresh(rr)
        assert (rr.accounts_payable_id, rr.settled_cdv_id) == (ap.id, None)
        assert b'no AP voucher has billed' in resp.data


# ------------------------------------------------------------------- reopening

class TestReopening:

    def test_the_administrator_reopens_a_settlement(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)
        _settle(client, rr)

        client.post(f'/receiving-reports/{rr.id}/reopen-settlement',
                    data={'reopen_reason': 'Settled against the wrong voucher'},
                    follow_redirects=True)

        db_session.refresh(rr)
        assert rr.status == 'approved'
        assert (rr.settled_cdv_id, rr.settled_by_id, rr.settled_at, rr.settle_reason) == \
            (None, None, None, None)
        assert rr.id in [r['id'] for r in billable_rrs_for(main_branch.id, vl_vendor.id)]
        row = (AuditLog.query.filter_by(module='receiving_reports', action='reopen_settlement',
                                        record_id=rr.id).first())
        assert row is not None and 'wrong voucher' in row.notes

    def test_reopening_needs_a_reason(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)
        _settle(client, rr)

        client.post(f'/receiving-reports/{rr.id}/reopen-settlement',
                    data={'reopen_reason': 'oops'}, follow_redirects=True)

        db_session.refresh(rr)
        assert rr.status == 'billed' and rr.settled_cdv_id is not None

    def test_staff_cannot_reopen(
            self, client, admin_user, staff_user, main_branch, vl_vendor, cash_account,
            db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)
        _settle(client, rr)
        staff = client.application.test_client()       # one client per user: a second
        _as(staff, staff_user, main_branch, db_session)  # login on the same client does not take

        staff.post(f'/receiving-reports/{rr.id}/reopen-settlement',
                   data={'reopen_reason': 'Trying to reopen as staff'}, follow_redirects=True)

        db_session.refresh(rr)
        assert rr.status == 'billed' and rr.settled_cdv_id is not None

    def test_cancelling_the_cdv_reopens_what_it_settled(self, client, db_session, admin_user,
                                                        main_branch):
        """The payment is reversed, so the receipt is unpaid again -- same transaction."""
        from app.utils import ph_now
        from tests.integration.test_cdv_views import (create_draft_cdv, login, make_vendor,
                                                      setup_accounts)
        login(client)
        _ap, _wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        create_draft_cdv(client, vendor, cash, cdv_number='1613', expense_lines=[
            {'description': 'Valves', 'amount': 500.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': None}])
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='1613').one()
        client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)
        db_session.refresh(cdv)
        assert cdv.status == 'posted'
        rr = _approved_rr(db_session, main_branch, vendor)
        _settle(client, rr)
        db_session.refresh(rr)
        assert rr.status == 'billed'

        resp = client.post(f'/cash-disbursements/{cdv.id}/cancel', data={
            'cancel_reason': 'Recorded against the wrong bank',
            'reversal_date': ph_now().date().isoformat()}, follow_redirects=True)

        db_session.refresh(cdv)
        db_session.refresh(rr)
        assert cdv.status == 'cancelled'
        assert (rr.status, rr.settled_cdv_id) == ('approved', None)
        assert b'Reopened as unbilled: Receiving Report 00684' in resp.data
        assert AuditLog.query.filter_by(module='receiving_reports', action='reopen_settlement',
                                        record_id=rr.id).first() is not None


# ------------------------------------------------------------------- the page

class TestDetailPage:

    def test_everyone_sees_what_settled_it(
            self, client, admin_user, staff_user, main_branch, vl_vendor, cash_account,
            db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        cdv = _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)
        _settle(client, rr)
        staff = client.application.test_client()
        _as(staff, staff_user, main_branch, db_session)

        html = staff.get(f'/receiving-reports/{rr.id}').get_data(as_text=True)

        assert 'Settled outside AP by CDV' in html
        assert f'href="/cash-disbursements/{cdv.id}"' in html
        assert f'action="/receiving-reports/{rr.id}/reopen-settlement"' not in html

    def test_only_the_administrator_is_offered_the_controls(
            self, client, admin_user, staff_user, main_branch, vl_vendor, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)

        staff = client.application.test_client()
        _as(staff, staff_user, main_branch, db_session)
        staff_html = staff.get(f'/receiving-reports/{rr.id}').get_data(as_text=True)
        _switch_user(client, admin_user, main_branch)
        admin_html = client.get(f'/receiving-reports/{rr.id}').get_data(as_text=True)

        assert 'Receiving Report 00684' in staff_html, 'the staff page must actually render'

        assert f'action="/receiving-reports/{rr.id}/settle"' not in staff_html
        assert f'action="/receiving-reports/{rr.id}/settle"' in admin_html
