"""Unit tests for the Sales Memo models (Credit/Debit memo).

Line math mirrors SalesInvoiceItem: VAT-inclusive extraction, and WHT computed on
Net-of-ROUNDED-VAT (Gross - rounded VAT), NOT the unrounded Gross/1.12 — the owner
formula (memory `wht-net-of-rounded-vat-formula`). Header totals mirror SalesInvoice:
subtotal = sum(line_total) [VAT-inclusive], total = subtotal - WHT.
"""
from decimal import Decimal

import pytest

from app.sales_memos.models import SalesMemo, SalesMemoItem, generate_memo_number

pytestmark = [pytest.mark.unit, pytest.mark.models, pytest.mark.credit_memos]


def _item(**kw):
    li = SalesMemoItem(**kw)
    li.calculate_amounts()
    return li


def test_calculate_amounts_extracts_inclusive_vat(app):
    li = _item(line_number=1, quantity=Decimal('1'), unit_price=Decimal('1120'),
               vat_rate=Decimal('12'))
    assert li.amount == Decimal('1120.00')
    assert li.line_total == Decimal('1120.00')
    assert li.vat_amount == Decimal('120.00')       # 1120 - 1120/1.12


def test_calculate_amounts_wht_on_net_of_rounded_vat(app):
    # Gross 1120, VAT 120 -> Net of VAT 1000 -> WHT @2% = 20.00
    li = _item(line_number=1, amount=Decimal('1120'), vat_rate=Decimal('12'),
               wt_rate=Decimal('2'))
    assert li.vat_amount == Decimal('120.00')
    assert li.wt_amount == Decimal('20.00')


def test_calculate_amounts_zero_vat(app):
    li = _item(line_number=1, amount=Decimal('500'), vat_rate=Decimal('0'))
    assert li.vat_amount == Decimal('0.00')
    assert li.line_total == Decimal('500.00')


def test_calculate_totals_sums_lines_and_nets_wht(app):
    memo = SalesMemo(memo_type='credit')
    memo.line_items = [
        _item(line_number=1, amount=Decimal('1120'), vat_rate=Decimal('12'), wt_rate=Decimal('2')),
        _item(line_number=2, amount=Decimal('560'), vat_rate=Decimal('12')),
    ]
    memo.calculate_totals()
    # subtotal is the VAT-inclusive sum (mirror SI); total = subtotal - WHT.
    assert memo.subtotal == Decimal('1680.00')
    assert memo.vat_amount == Decimal('180.00')          # 120 + 60
    assert memo.withholding_tax_amount == Decimal('20.00')
    assert memo.total_amount == Decimal('1660.00')       # 1680 - 20


def test_generate_memo_number_is_plain_digit_by_type(app, db_session):
    cm = generate_memo_number('credit')
    dm = generate_memo_number('debit')
    assert cm == '00001'
    assert dm == '00001'


def test_generate_memo_number_increments_within_type(app, db_session):
    from app.utils import ph_now
    today = ph_now().date()
    n1 = generate_memo_number('credit')
    db_session.add(SalesMemo(
        memo_type='credit', memo_number=n1, memo_date=today,
        sales_invoice_id=1, original_invoice_number='SI-1', customer_id=1,
        customer_name='X', reason='return', status='draft'))
    db_session.commit()
    assert generate_memo_number('credit') == '00002'
    # A different type keeps its own sequence.
    assert generate_memo_number('debit') == '00001'


def _memo(memo_type, number, branch_id=None):
    from app.utils import ph_now
    return SalesMemo(memo_type=memo_type, memo_number=number, memo_date=ph_now().date(),
                     sales_invoice_id=1, original_invoice_number='SI-1', customer_id=1,
                     customer_name='X', reason='return', status='draft',
                     branch_id=branch_id)


def test_generate_memo_number_is_per_type_and_branch_under_branch_scope(
        app, db_session, main_branch, branch_manila):
    from app.settings import AppSettings
    AppSettings.set_setting('document_number_scope', 'branch')
    db_session.add_all([
        _memo('credit', '00001', main_branch.id),
        _memo('debit', '00050', main_branch.id),
        _memo('credit', '00030', branch_manila.id),
    ])
    db_session.commit()
    # this branch's CREDIT series only -- neither the debit run nor the other
    # branch's credit run may lead it
    assert generate_memo_number('credit', main_branch.id) == '00002'


def test_generate_memo_number_does_not_merge_credit_and_debit(app, db_session, main_branch):
    """memo_type is UNCONDITIONAL -- it must hold under BOTH scopes."""
    from app.settings import AppSettings
    db_session.add(_memo('debit', '00090', main_branch.id))
    db_session.commit()
    assert generate_memo_number('credit', main_branch.id) == '00001'
    AppSettings.set_setting('document_number_scope', 'branch')
    assert generate_memo_number('credit', main_branch.id) == '00001'


def test_generate_memo_number_stays_per_type_only_under_company_scope(
        app, db_session, main_branch, branch_manila):
    """CONTROL -- no setting row, so the other branch's credit memo DOES lead."""
    db_session.add_all([
        _memo('credit', '00001', main_branch.id),
        _memo('credit', '00030', branch_manila.id),
    ])
    db_session.commit()
    assert generate_memo_number('credit', main_branch.id) == '00031'


def test_generate_memo_number_continues_from_legacy_literal_number(app, db_session):
    from app.utils import ph_now
    today = ph_now().date()
    db_session.add(SalesMemo(
        memo_type='credit', memo_number='680', memo_date=today,
        sales_invoice_id=1, original_invoice_number='SI-1', customer_id=1,
        customer_name='X', reason='return', status='draft'))
    db_session.commit()
    assert generate_memo_number('credit') == '00681'


def test_generate_memo_number_ignores_legacy_prefixed_numbers(app, db_session):
    from app.utils import ph_now
    today = ph_now().date()
    db_session.add(SalesMemo(
        memo_type='credit', memo_number='CM-2026-07-0030', memo_date=today,
        sales_invoice_id=1, original_invoice_number='SI-1', customer_id=1,
        customer_name='X', reason='return', status='draft'))
    db_session.commit()
    assert generate_memo_number('credit') == '00001'
