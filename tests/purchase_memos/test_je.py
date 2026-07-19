"""Vendor Debit Memo journal-entry builder: balance + per-leg tie-out to the
memo header. Mirrors tests/integration/test_credit_memo_je.py's structure --
post_purchase_memo_je is the buy-side inverse of sales_memos.je's credit-memo
branch (AP-Trade/WHT-Payable via app.posting.control_accounts, Purchase
Returns/Vendor Credits via app.purchase_memos.service.resolve_memo_account --
Task 2's verified interface correction)."""
from decimal import Decimal

import pytest

from app.purchase_memos.je import post_purchase_memo_je

from tests.purchase_memos.conftest import CTRL, leg

pytestmark = [pytest.mark.unit, pytest.mark.purchase_memos]


def test_debit_memo_je_ties_and_inverts(app_ctx, posted_ap_factory):
    memo = posted_ap_factory(destination='ap', subtotal='1000', vat='120', wht='10')  # gross 1120, net-of-wht 1110
    je = post_purchase_memo_je(memo, user_id=1)
    assert je.is_balanced
    ap = leg(je, code=CTRL['ap_trade'])
    wp = leg(je, code=CTRL['wht_payable'])
    pr = leg(je, code=CTRL['purchase_returns'])
    assert ap.debit_amount == Decimal('1110.00')       # destination = gross - wht
    assert wp.debit_amount == Decimal('10.00')          # WHT unwound
    assert pr.credit_amount == Decimal('1000.00')       # net
    assert leg(je, input_vat=True).credit_amount == Decimal('120.00')
    assert je.total_debit == je.total_credit == Decimal('1120.00')


def test_je_builder_does_not_touch_referenced_bill_balance(app_ctx, posted_ap_factory):
    """Adjudication 1 (Task 4): post_purchase_memo_je builds the JE ONLY -- the
    AP-balance reduction moved to app/purchase_memos/views.py::_apply_memo_to_ap
    (called from debit_post), mirroring sales_memos/je.py::post_memo_je, which
    likewise never touches the AR balance. See tests/purchase_memos/test_crud_gating.py
    for the view-layer reduction test (single reduction site, proven end-to-end)."""
    memo = posted_ap_factory(destination='ap', subtotal='1000', vat='120', wht='0')
    before = memo.accounts_payable.balance
    post_purchase_memo_je(memo, user_id=1)
    assert memo.accounts_payable.balance == before   # unchanged by the JE builder


def test_je_builder_with_wht_still_does_not_touch_bill_balance(app_ctx, posted_ap_factory):
    memo = posted_ap_factory(destination='ap', subtotal='1000', vat='120', wht='10')
    before = memo.accounts_payable.balance
    post_purchase_memo_je(memo, user_id=1)
    assert memo.accounts_payable.balance == before   # unchanged by the JE builder


def test_cash_and_vendor_credit_destinations(app_ctx, posted_ap_factory):
    m1 = posted_ap_factory(destination='cash_refund', subtotal='1000', vat='120', wht='0')
    before_balance = m1.accounts_payable.balance
    je1 = post_purchase_memo_je(m1, user_id=1)
    assert leg(je1, id=m1.cash_account_id).debit_amount == Decimal('1120.00')
    assert m1.accounts_payable.balance == before_balance   # unchanged -- not the 'ap' destination

    m2 = posted_ap_factory(destination='vendor_credit', subtotal='1000', vat='120', wht='0')
    je2 = post_purchase_memo_je(m2, user_id=1)
    assert leg(je2, code=CTRL['vendor_credits']).debit_amount == Decimal('1120.00')


def test_unassigned_control_is_friendly(app_ctx, posted_ap_factory_no_ctrl):
    with pytest.raises(ValueError):
        post_purchase_memo_je(posted_ap_factory_no_ctrl(), 1)


def test_credit_memo_je_ties_and_inverts(app_ctx, posted_ap_credit_factory):
    memo = posted_ap_credit_factory(destination='ap', subtotal='1000', vat='120', wht='10')
    je = post_purchase_memo_je(memo, user_id=1)
    assert je.is_balanced
    ap = leg(je, code=CTRL['ap_trade'])
    wp = leg(je, code=CTRL['wht_payable'])
    exp = leg(je, id=memo.line_items[0].account_id)
    assert exp.debit_amount == Decimal('1000.00')       # net
    assert leg(je, input_vat=True).debit_amount == Decimal('120.00')
    assert wp.credit_amount == Decimal('10.00')          # WHT withheld on the new charge
    assert ap.credit_amount == Decimal('1110.00')        # destination = gross - wht
    assert je.total_debit == je.total_credit == Decimal('1120.00')


def test_credit_je_builder_does_not_touch_referenced_bill_balance(app_ctx, posted_ap_credit_factory):
    memo = posted_ap_credit_factory(destination='ap', subtotal='1000', vat='120', wht='0')
    before = memo.accounts_payable.balance
    post_purchase_memo_je(memo, user_id=1)
    assert memo.accounts_payable.balance == before   # unchanged by the JE builder


def test_credit_cash_and_vendor_credit_destinations(app_ctx, posted_ap_credit_factory):
    m1 = posted_ap_credit_factory(destination='cash_refund', subtotal='1000', vat='120', wht='0')
    je1 = post_purchase_memo_je(m1, user_id=1)
    assert leg(je1, id=m1.cash_account_id).credit_amount == Decimal('1120.00')

    m2 = posted_ap_credit_factory(destination='vendor_credit', subtotal='1000', vat='120', wht='0')
    je2 = post_purchase_memo_je(m2, user_id=1)
    assert leg(je2, code=CTRL['vendor_credits']).credit_amount == Decimal('1120.00')


def test_credit_memo_no_wht_omits_wht_leg(app_ctx, posted_ap_credit_factory):
    memo = posted_ap_credit_factory(destination='ap', subtotal='1000', vat='120', wht='0')
    je = post_purchase_memo_je(memo, user_id=1)
    assert je.is_balanced
    from app.journal_entries.models import JournalEntryLine
    from app.accounts.models import Account
    from app import db
    for l in JournalEntryLine.query.filter_by(entry_id=je.id).all():
        acct = db.session.get(Account, l.account_id)
        assert acct.code != CTRL['wht_payable']


def test_credit_unassigned_vendor_credits_is_friendly(app_ctx, posted_ap_credit_factory_no_ctrl):
    with pytest.raises(ValueError):
        post_purchase_memo_je(posted_ap_credit_factory_no_ctrl(destination='vendor_credit'), 1)
