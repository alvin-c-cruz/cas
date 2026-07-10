import pytest
from decimal import Decimal
from datetime import date
from app import db
from app.accounts.models import Account
from app.withholding_tax.models import WithholdingTax
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.accounts_payable.views import _wht_payable_buckets

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


def _bill_with_lines(lines, wt_total):
    # lines = [(WithholdingTax, wt_amount)]
    ap = AccountsPayable(ap_number=f'AP-TEST-{id(lines)}', ap_date=date(2026, 1, 1),
                         due_date=date(2026, 1, 31), vendor_id=1, vendor_name='Test Vendor',
                         subtotal=Decimal('0.00'), vat_amount=Decimal('0.00'),
                         withholding_tax_amount=Decimal(str(wt_total)), total_amount=Decimal('0.00'))
    db.session.add(ap); db.session.flush()
    for i, (w, amt) in enumerate(lines, 1):
        it = AccountsPayableItem(ap_id=ap.id, line_number=i, description=f'Line {i}',
                                 amount=Decimal('0.00'), wt_id=(w.id if w else None),
                                 wt_amount=Decimal(str(amt)))
        db.session.add(it)
    db.session.flush()
    return ap


def test_buckets_split_by_rate_account(db_session):
    fallback = _acct('20301', 'Withholding Tax Payable - Expanded')
    a1 = _acct('22105-1', 'WHT Payable - 1%')
    a2 = _acct('22105-2', 'WHT Payable - 2%')
    w1 = _wht('WC158', 1, a1)
    w2 = _wht('WC160', 2, a2)
    ap = _bill_with_lines([(w1, '100.00'), (w2, '200.00'), (w1, '50.00')], wt_total='350.00')

    buckets = _wht_payable_buckets(ap, fallback)
    by_code = {acct.code: amt for acct, amt in buckets}
    assert by_code == {'22105-1': Decimal('150.00'), '22105-2': Decimal('200.00')}
    assert sum(amt for _, amt in buckets) == Decimal('350.00')   # total invariant


def test_buckets_fall_back_when_atc_has_no_payable(db_session):
    fallback = _acct('20301', 'Withholding Tax Payable - Expanded')
    w = _wht('WCX', 5, None)   # no payable account
    ap = _bill_with_lines([(w, '75.00')], wt_total='75.00')
    buckets = _wht_payable_buckets(ap, fallback)
    assert [(a.code, amt) for a, amt in buckets] == [('20301', Decimal('75.00'))]


def test_override_diff_applied_to_largest_bucket(db_session):
    fallback = _acct('20301', 'WHT Payable')
    a1 = _acct('22105-1', 'WHT 1%'); a2 = _acct('22105-2', 'WHT 2%')
    w1 = _wht('WC158', 1, a1); w2 = _wht('WC160', 2, a2)
    # lines sum to 300 but the bill's WHT was overridden to 310 -> +10 to the largest (a2=200)
    ap = _bill_with_lines([(w1, '100.00'), (w2, '200.00')], wt_total='310.00')
    by_code = {a.code: amt for a, amt in _wht_payable_buckets(ap, fallback)}
    assert by_code == {'22105-1': Decimal('100.00'), '22105-2': Decimal('210.00')}


def test_override_below_line_totals_raises(db_session):
    fb = _acct('20301', 'WHT Payable')
    a1 = _acct('22105-1', 'WHT 1%'); a2 = _acct('22105-2', 'WHT 2%')
    w1 = _wht('WC158', 1, a1); w2 = _wht('WC160', 2, a2)
    ap = _bill_with_lines([(w1, '10.00'), (w2, '200.00')], wt_total='1.00')  # override 1 << 210
    with pytest.raises(ValueError):
        _wht_payable_buckets(ap, fb)


# ---------------------------------------------------------------------------
# The empty-bucket gap. CDV was fixed for this (a4092f8, "FINDING 1 (Critical)"
# in test_cdv_wht_buckets.py); AP never was, though it is the same routine.
#
# `if diff != 0 and ordered:` silently returns [] when the bill carries a WHT
# total but no line contributes any -- so `_post_ap_je` books no WHT-payable leg
# and its residual absorber quietly adds the amount to the first expense line's
# debit (views.py:1367). Expense overstated, WHT payable unrecorded, JE balanced.
# Dr == Cr proves nothing.
# ---------------------------------------------------------------------------

def test_pure_override_with_no_line_wht_uses_fallback(db_session):
    """A bill-level WHT with no line-level WHT must book to the 20301 fallback."""
    fallback = _acct('20301', 'Withholding Tax Payable - Expanded')
    ap = _bill_with_lines([], wt_total='50.00')
    assert [(a.code, amt) for a, amt in _wht_payable_buckets(ap, fallback)] == [
        ('20301', Decimal('50.00'))
    ]


def test_pure_override_with_no_bucket_and_no_fallback_raises(db_session):
    """No line WHT and no 20301 in the COA: fail loudly, never return [] and let the
    residual absorber bury the amount in an expense line."""
    ap = _bill_with_lines([], wt_total='50.00')
    with pytest.raises(ValueError, match='Withholding Tax Payable'):
        _wht_payable_buckets(ap, None)


def test_lines_present_but_none_carry_wht_uses_fallback(db_session):
    """Same gap, reached via lines that exist but carry zero WHT."""
    fallback = _acct('20301', 'Withholding Tax Payable - Expanded')
    ap = _bill_with_lines([(None, '0.00'), (None, '0.00')], wt_total='30.00')
    assert [(a.code, amt) for a, amt in _wht_payable_buckets(ap, fallback)] == [
        ('20301', Decimal('30.00'))
    ]
