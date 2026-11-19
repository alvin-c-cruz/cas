"""Settling a receipt by the cash voucher that paid it: pick the voucher, approvers may do it, and CAS points out a
voucher that looks like it paid ahead (RRP-1 A + RRP-2 B, owner 14 Nov 2026; work order
2026-11-02-recommendation-rr-linked-to-prepaid-cdv).

1. The settle box offers the vendor's posted CDVs that pay no AP voucher (any branch) -- no typing.
2. The CDV page lists the receipts it settled.
3. "Paid already?": on a submitted or approved-unbilled receipt, and in the AP voucher's receipt picker, a posted CDV to
   the same vendor dated within 30 days before the receipt that pays no AP voucher and settles no receipt is named.
4. The wording covers any receipt a CDV paid, not only pre-AP-module ones.
RRP-2 B: approvers (accountant or full access) may settle and reopen; this changes the 3 Oct 2026 administrator-only rule.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayable
from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
from app.purchase_billing import billable_rrs_for
from tests.integration.test_rr_settled_by_cdv import _approved_rr, _as, _switch_user  # noqa: F401
from tests.integration.test_receiving_reports_lifecycle import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]

RECEIPT = date(2026, 7, 29)          # _approved_rr's receipt date
REASON = 'Paid ahead by legacy EXTRA CV 1197 before delivery'


def _cdv(db_session, branch, vendor, cash_account, number, when=date(2026, 7, 20), status='posted',
         total='1000.00'):
    cdv = CashDisbursementVoucher(branch_id=branch.id, cdv_number=number, cdv_date=when, payee_type='vendor',
                                  payee_id=vendor.id, vendor_id=vendor.id, vendor_name=vendor.name,
                                  cash_account_id=cash_account.id, status=status, total_amount=Decimal(total))
    db_session.add(cdv); db_session.commit()
    return cdv


def _pays_an_apv(db_session, cdv, branch, vendor):
    ap = AccountsPayable(ap_number='AP-' + cdv.cdv_number, ap_date=cdv.cdv_date, due_date=cdv.cdv_date,
                         vendor_id=vendor.id, vendor_name=vendor.name, branch_id=branch.id, status='posted')
    db_session.add(ap); db_session.commit()
    db_session.add(CDVApLine(cdv_id=cdv.id, line_number=1, ap_id=ap.id, ap_number=ap.ap_number,
                             original_balance=Decimal('1000.00'), amount_applied=Decimal('1000.00')))
    db_session.commit()


class TestThePicker:

    def test_the_settle_box_lists_the_vendors_free_posted_cdvs(
            self, client, admin_user, main_branch, branch_manila, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        free = _cdv(db_session, main_branch, vl_vendor, cash_account, '1700')
        other_branch = _cdv(db_session, branch_manila, vl_vendor, cash_account, '1197E')
        _cdv(db_session, main_branch, vl_vendor, cash_account, '1701', status='draft')
        billed = _cdv(db_session, main_branch, vl_vendor, cash_account, '1702')
        _pays_an_apv(db_session, billed, main_branch, vl_vendor)
        _login(client, admin_user, main_branch)

        html = client.get(f'/receiving-reports/{rr.id}').get_data(as_text=True)

        assert 'name="cdv_id"' in html
        assert f'value="{free.id}"' in html and f'value="{other_branch.id}"' in html
        assert 'CDV 1700' in html and 'CDV 1197E' in html
        assert 'CDV 1701' not in html, 'a draft CDV cannot settle'
        assert 'CDV 1702' not in html, 'a CDV that pays an AP voucher is not a candidate'

    def test_settling_by_the_picked_cdv(self, client, admin_user, main_branch, vl_vendor, cash_account,
                                        db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        cdv = _cdv(db_session, main_branch, vl_vendor, cash_account, '1700')
        _login(client, admin_user, main_branch)
        client.post(f'/receiving-reports/{rr.id}/settle', data={'cdv_id': cdv.id, 'settle_reason': REASON},
                    follow_redirects=True)
        db_session.refresh(rr)
        assert (rr.status, rr.settled_cdv_id) == ('billed', cdv.id)


class TestApprovers:

    def test_an_accountant_may_settle_and_reopen(self, client, accountant_user, main_branch, vl_vendor,
                                                 cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        cdv = _cdv(db_session, main_branch, vl_vendor, cash_account, '1700')
        _as(client, accountant_user, main_branch, db_session)
        html = client.get(f'/receiving-reports/{rr.id}').get_data(as_text=True)
        assert f'action="/receiving-reports/{rr.id}/settle"' in html
        client.post(f'/receiving-reports/{rr.id}/settle', data={'cdv_id': cdv.id, 'settle_reason': REASON},
                    follow_redirects=True)
        db_session.refresh(rr)
        assert rr.settled_cdv_id == cdv.id
        client.post(f'/receiving-reports/{rr.id}/reopen-settlement',
                    data={'reopen_reason': 'settled against the wrong voucher'}, follow_redirects=True)
        db_session.refresh(rr)
        assert (rr.status, rr.settled_cdv_id) == ('approved', None)

    def test_staff_still_may_not(self, client, staff_user, main_branch, vl_vendor, cash_account, db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        cdv = _cdv(db_session, main_branch, vl_vendor, cash_account, '1700')
        _as(client, staff_user, main_branch, db_session)
        resp = client.post(f'/receiving-reports/{rr.id}/settle', data={'cdv_id': cdv.id, 'settle_reason': REASON},
                           follow_redirects=True)
        db_session.refresh(rr)
        assert rr.settled_cdv_id is None
        assert b'Only an approver' in resp.data


class TestTheCdvPage:

    def test_it_lists_the_receipts_it_settled(self, client, admin_user, main_branch, vl_vendor, cash_account,
                                              db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        cdv = _cdv(db_session, main_branch, vl_vendor, cash_account, '1700')
        _login(client, admin_user, main_branch)
        client.post(f'/receiving-reports/{rr.id}/settle', data={'cdv_id': cdv.id, 'settle_reason': REASON},
                    follow_redirects=True)
        html = client.get(f'/cash-disbursements/{cdv.id}').get_data(as_text=True)
        assert 'data-cdv-settled-rrs' in html
        assert f'href="/receiving-reports/{rr.id}"' in html and 'RR 00684' in html


class TestPaidAlready:

    def test_a_recent_free_cdv_is_pointed_out(self, client, admin_user, main_branch, vl_vendor, cash_account,
                                              db_session):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account, '1700', when=RECEIPT - timedelta(days=9))
        _login(client, admin_user, main_branch)
        html = client.get(f'/receiving-reports/{rr.id}').get_data(as_text=True)
        assert 'data-rr-paid-already' in html and 'CDV 1700' in html

    @pytest.mark.parametrize('case', ['too_old', 'pays_an_apv', 'after_the_receipt', 'settles_another'])
    def test_no_hint_when_it_does_not_fit(self, client, admin_user, main_branch, vl_vendor, cash_account,
                                          db_session, case):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        when = {'too_old': RECEIPT - timedelta(days=31), 'after_the_receipt': RECEIPT + timedelta(days=1)
                }.get(case, RECEIPT - timedelta(days=5))
        cdv = _cdv(db_session, main_branch, vl_vendor, cash_account, '1700', when=when)
        if case == 'pays_an_apv':
            _pays_an_apv(db_session, cdv, main_branch, vl_vendor)
        if case == 'settles_another':
            other = _approved_rr(db_session, main_branch, vl_vendor, number='00699')
            other.status, other.settled_cdv_id = 'billed', cdv.id
            db_session.commit()
        _login(client, admin_user, main_branch)
        assert 'data-rr-paid-already' not in client.get(f'/receiving-reports/{rr.id}').get_data(as_text=True)

    def test_the_ap_receipt_picker_carries_the_hint(self, db_session, main_branch, vl_vendor, cash_account):
        rr = _approved_rr(db_session, main_branch, vl_vendor)
        _cdv(db_session, main_branch, vl_vendor, cash_account, '1700', when=RECEIPT - timedelta(days=3))
        quiet = _approved_rr(db_session, main_branch, vl_vendor, number='00700')
        quiet.receipt_date = RECEIPT + timedelta(days=60)
        db_session.commit()
        rows = {r['rr_number']: r for r in billable_rrs_for(main_branch.id, vl_vendor.id)}
        assert 'CDV 1700' in (rows[rr.rr_number]['paid_hint'] or '')
        assert rows['00700']['paid_hint'] is None
