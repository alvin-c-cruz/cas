import pytest
from decimal import Decimal
from datetime import date
from app import db
from app.accounts.models import Account
from app.withholding_tax.models import WithholdingTax
from app.branches.models import Branch
from app.vendors.models import Vendor
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
from app.cash_disbursements.views import _cdv_wht_payable_buckets

pytestmark = [pytest.mark.integration]


def _acct(code, name):
    a = Account(code=code, name=name, account_type='Liability', classification='Current',
                normal_balance='credit', is_active=True)
    db.session.add(a); db.session.flush()
    return a


def _wht(code, rate, payable_acct):
    w = WithholdingTax(code=code, name=code, rate=Decimal(str(rate)), is_active=True,
                       payable_account_id=(payable_acct.id if payable_acct else None))
    db.session.add(w); db.session.flush()
    return w


def _branch():
    b = Branch(code='MAIN', name='Main Branch', is_active=True)
    db.session.add(b); db.session.flush()
    return b


def _vendor():
    v = Vendor(code='V0001', name='Test Vendor', is_active=True)
    db.session.add(v); db.session.flush()
    return v


def _cash_acct():
    a = Account(code='10101', name='Cash on Hand', account_type='Asset', classification='Current',
                normal_balance='debit', is_active=True)
    db.session.add(a); db.session.flush()
    return a


def _cdv_with_expense_lines(lines):
    branch = _branch()
    vendor = _vendor()
    cash_account = _cash_acct()
    cdv = CashDisbursementVoucher(
        branch_id=branch.id, cdv_number=f'CDV-TEST-{id(lines)}', cdv_date=date(2026, 1, 1),
        vendor_id=vendor.id, vendor_name=vendor.name, cash_account_id=cash_account.id,
    )
    db.session.add(cdv); db.session.flush()
    for i, (w, amt) in enumerate(lines, 1):
        # line_total > 0 so the positive-Section-B WHT guard in
        # _cdv_wht_payable_buckets lets these lines through (mirrors real data,
        # where a positive wt_amount only ever occurs on a positive expense line).
        el = CDVExpenseLine(cdv_id=cdv.id, line_number=i, description=f'Line {i}',
                            amount=Decimal('100.00'), line_total=Decimal('100.00'),
                            wt_id=(w.id if w else None), wt_amount=Decimal(str(amt)))
        db.session.add(el)
    db.session.flush()
    return cdv


def test_cdv_buckets_split_by_rate_account(db_session):
    fb = _acct('20301', 'WHT Payable')
    a1 = _acct('22105-1', 'WHT 1%'); a2 = _acct('22105-2', 'WHT 2%')
    w1 = _wht('WC158', 1, a1); w2 = _wht('WC160', 2, a2)
    cdv = _cdv_with_expense_lines([(w1, '100.00'), (w2, '200.00')])
    by_code = {a.code: amt for a, amt in _cdv_wht_payable_buckets(cdv, fb)}
    assert by_code == {'22105-1': Decimal('100.00'), '22105-2': Decimal('200.00')}


def test_cdv_buckets_fall_back(db_session):
    fb = _acct('20301', 'WHT Payable')
    w = _wht('WCX', 5, None)
    cdv = _cdv_with_expense_lines([(w, '40.00')])
    assert [(a.code, amt) for a, amt in _cdv_wht_payable_buckets(cdv, fb)] == [('20301', Decimal('40.00'))]
