"""Unit tests for the Purchase Memo models (Vendor Debit/Credit memo).

Line math mirrors AccountsPayableItem: VAT-inclusive extraction, and WHT computed
on Net-of-ROUNDED-VAT (Gross - rounded VAT), NOT the unrounded Gross/1.12 -- the
owner formula (memory `wht-net-of-rounded-vat-formula`). Header totals mirror
AccountsPayable: subtotal = sum(line_total) [VAT-inclusive], total = subtotal - WHT.

NOTE on divergence from the task-1 brief's starter snippet: the brief constructed
`PurchaseMemoItem(memo_id=..., description=..., line_total=...)`. The mirrored
model (cloned from SalesMemoItem, which has neither a `description` column nor a
`memo_id` FK) uses `purchase_memo_id` as the FK column name and has no
`description` field -- description lives on the referenced AccountsPayableItem.
`calculate_amounts()` derives `line_total`/`vat_amount`/`wt_amount` FROM `amount`
(VAT-inclusive), not the reverse, so the tests below set `amount=`, mirroring
`test_sales_memo_model.py`. Per the task instructions, the mirror wins over the
brief's starter code; the expected numeric assertions (VAT=120.00 on a 1120 gross
line, WHT=10.00 @1% of the 1000 net-of-VAT base) are unchanged from the brief.
"""
from decimal import Decimal

import pytest

from app import db
from app.purchase_memos.models import PurchaseMemo, PurchaseMemoItem, generate_purchase_memo_number

pytestmark = [pytest.mark.unit, pytest.mark.models]


def _item(**kw):
    li = PurchaseMemoItem(**kw)
    li.calculate_amounts()
    return li


def test_calculate_amounts_extracts_inclusive_vat(app_ctx):
    li = _item(line_number=1, quantity=Decimal('1'), unit_price=Decimal('1120'),
               vat_rate=Decimal('12'))
    assert li.amount == Decimal('1120.00')
    assert li.line_total == Decimal('1120.00')
    assert li.vat_amount == Decimal('120.00')       # 1120 - 1120/1.12


def test_line_reversal_math(app_ctx, a_posted_ap, one_branch):
    """Mirrors the task-1 brief's test_line_reversal_math, adapted to the true
    (mirrored) field names -- see module docstring."""
    m = PurchaseMemo(
        memo_type='debit', memo_number=generate_purchase_memo_number('debit'),
        vendor_id=a_posted_ap.vendor_id,
        accounts_payable_id=a_posted_ap.id, original_ap_number=a_posted_ap.ap_number,
        vendor_name=a_posted_ap.vendor_name, branch_id=one_branch.id,
        memo_date=a_posted_ap.ap_date, destination='ap', reason='return',
    )
    db.session.add(m)
    db.session.flush()
    it = PurchaseMemoItem(
        purchase_memo_id=m.id,
        accounts_payable_item_id=a_posted_ap.line_items[0].id,
        line_number=1, amount=Decimal('1120.00'),
        vat_rate=Decimal('12'), wt_rate=Decimal('1'),
    )
    it.calculate_amounts()
    assert it.vat_amount == Decimal('120.00')            # 1120 inclusive -> 120 VAT
    assert it.wt_amount == Decimal('10.00')               # 1% of 1000 net-of-VAT


def test_calculate_amounts_zero_vat(app_ctx):
    li = _item(line_number=1, amount=Decimal('500'), vat_rate=Decimal('0'))
    assert li.vat_amount == Decimal('0.00')
    assert li.line_total == Decimal('500.00')


def test_calculate_totals_sums_lines_and_nets_wht(app_ctx):
    memo = PurchaseMemo(memo_type='debit')
    memo.line_items = [
        _item(line_number=1, amount=Decimal('1120'), vat_rate=Decimal('12'), wt_rate=Decimal('2')),
        _item(line_number=2, amount=Decimal('560'), vat_rate=Decimal('12')),
    ]
    memo.calculate_totals()
    # subtotal is the VAT-inclusive sum (mirror AP); total = subtotal - WHT.
    assert memo.subtotal == Decimal('1680.00')
    assert memo.vat_amount == Decimal('180.00')          # 120 + 60
    assert memo.withholding_tax_amount == Decimal('20.00')
    assert memo.total_amount == Decimal('1660.00')       # 1680 - 20


def test_number_prefix(app_ctx):
    assert generate_purchase_memo_number('debit').startswith('VDM-')
    assert generate_purchase_memo_number('credit').startswith('VCM-')


def test_generate_purchase_memo_number_increments_within_type(app_ctx, a_posted_ap, one_branch):
    from app.utils import ph_now
    today = ph_now().date()
    n1 = generate_purchase_memo_number('debit')
    db.session.add(PurchaseMemo(
        memo_type='debit', memo_number=n1, memo_date=today,
        accounts_payable_id=a_posted_ap.id, original_ap_number=a_posted_ap.ap_number,
        vendor_id=a_posted_ap.vendor_id, vendor_name=a_posted_ap.vendor_name,
        branch_id=one_branch.id, reason='return', status='draft'))
    db.session.commit()
    assert generate_purchase_memo_number('debit') == f'VDM-{today.year:04d}-{today.month:02d}-0002'
    # A different type keeps its own sequence.
    assert generate_purchase_memo_number('credit') == f'VCM-{today.year:04d}-{today.month:02d}-0001'
