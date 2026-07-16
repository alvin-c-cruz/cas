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


def test_ap_destination_reduces_referenced_bill_balance(app_ctx, posted_ap_factory):
    memo = posted_ap_factory(destination='ap', subtotal='1000', vat='120', wht='0')
    before = memo.accounts_payable.balance
    post_purchase_memo_je(memo, user_id=1)
    assert memo.accounts_payable.balance == before - Decimal('1120.00')


def test_ap_destination_with_wht_reduces_bill_by_net_of_wht(app_ctx, posted_ap_factory):
    memo = posted_ap_factory(destination='ap', subtotal='1000', vat='120', wht='10')
    before = memo.accounts_payable.balance
    post_purchase_memo_je(memo, user_id=1)
    assert memo.accounts_payable.balance == before - Decimal('1110.00')


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
