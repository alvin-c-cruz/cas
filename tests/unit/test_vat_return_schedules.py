import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.reports.vat_return import (
    build_vat_return_schedules, reconcile_vat_return,
    SALES_BOX_BY_NATURE, INPUT_BOX_BY_NATURE,
)

pytestmark = [pytest.mark.unit]

Z = Decimal('0.00')


def _customer(code='VR-CUST'):
    from app.customers.models import Customer
    c = Customer(code=code, name='Test Customer', tin='111-222-333-000',
                 address='1 Rizal St')
    db.session.add(c); db.session.commit()
    return c


def _vendor(code='VR-VEND'):
    from app.vendors.models import Vendor
    v = Vendor(code=code, name='Test Vendor', tin='444-555-666-000',
               address='2 Mabini St')
    db.session.add(v); db.session.commit()
    return v


def _posted_crv(branch, cash_acct, rev_acct, nature, code, amount, vat,
                when=date(2025, 8, 10)):
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    cust = _customer(code=f'VR-C-{nature}-{amount}')
    crv = CashReceiptVoucher(
        branch_id=branch.id, crv_number=f'CRV-{nature}-{amount}',
        crv_date=when, customer_id=cust.id, customer_name=cust.name,
        customer_tin=cust.tin, cash_account_id=cash_acct.id, status='posted')
    crv.revenue_lines.append(CRVRevenueLine(
        line_number=1, description='sale', amount=Decimal(str(amount)),
        vat_rate=Decimal('12.00'), vat_category=code, vat_nature=nature,
        line_total=Decimal(str(amount)), vat_amount=Decimal(str(vat)),
        account_id=rev_acct.id))
    db.session.add(crv); db.session.commit()
    return crv


def _posted_cdv(branch, cash_acct, exp_acct, nature, code, amount, vat,
                when=date(2025, 8, 10)):
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    vend = _vendor(code=f'VR-V-{nature}-{amount}')
    cdv = CashDisbursementVoucher(
        branch_id=branch.id, cdv_number=f'CDV-{nature}-{amount}',
        cdv_date=when, vendor_id=vend.id, vendor_name=vend.name,
        vendor_tin=vend.tin, cash_account_id=cash_acct.id, status='posted')
    cdv.expense_lines.append(CDVExpenseLine(
        line_number=1, description='buy', amount=Decimal(str(amount)),
        vat_rate=Decimal('12.00'), vat_category=code, vat_nature=nature,
        line_total=Decimal(str(amount)), vat_amount=Decimal(str(vat)),
        account_id=exp_acct.id))
    db.session.add(cdv); db.session.commit()
    return cdv


class TestBoxMaps:
    def test_sales_natures_map_to_part_I_boxes(self):
        assert SALES_BOX_BY_NATURE['regular'] == '12A'
        assert SALES_BOX_BY_NATURE['zero_export'] == '12B'
        assert SALES_BOX_BY_NATURE['zero_other'] == '12B'
        assert SALES_BOX_BY_NATURE['exempt'] == '12C'
        assert SALES_BOX_BY_NATURE['government'] == '12D'
        assert SALES_BOX_BY_NATURE['unclassified'] == 'unclassified'

    def test_all_eight_purchase_natures_map_to_part_II_boxes(self):
        from app.vat_categories.models import PURCHASE_NATURES
        for n in PURCHASE_NATURES:
            assert n in INPUT_BOX_BY_NATURE, n
        assert INPUT_BOX_BY_NATURE['capital_goods'] == '18AB'
        assert INPUT_BOX_BY_NATURE['not_qualified'] == '18G'


class TestSchedules:
    def test_regular_sale_lands_in_12A_with_base_and_tax(
            self, db_session, main_branch, cash_account, revenue_account):
        _posted_crv(main_branch, cash_account, revenue_account,
                    'regular', 'V12', 11200, 1200)
        s = build_vat_return_schedules(2025, 3)['sales_schedule']
        row_12a = next(r for r in s['rows'] if r['box'] == '12A')
        assert row_12a['base'] == Decimal('10000.00')
        assert row_12a['tax'] == Decimal('1200.00')
        assert s['total_tax'] == Decimal('1200.00')

    def test_part_I_always_lists_all_four_boxes_even_when_empty(
            self, db_session, main_branch):
        s = build_vat_return_schedules(2025, 3)['sales_schedule']
        boxes = [r['box'] for r in s['rows']]
        assert boxes[:4] == ['12A', '12B', '12C', '12D']  # always foots, even at zero

    def test_unclassified_sale_is_its_own_line_never_folded_into_12A(
            self, db_session, main_branch, cash_account, revenue_account):
        _posted_crv(main_branch, cash_account, revenue_account,
                    None, '', 11200, 1200)  # NULL nature -> 'unclassified'
        s = build_vat_return_schedules(2025, 3)['sales_schedule']
        row_12a = next(r for r in s['rows'] if r['box'] == '12A')
        assert row_12a['base'] == Z and row_12a['tax'] == Z
        assert s['unclassified_count'] == 1
        assert any(r.get('unclassified') for r in s['rows'])
        assert s['total_tax'] == Decimal('1200.00')  # still footed into the total

    def test_capital_goods_purchase_lands_in_18AB(
            self, db_session, main_branch, cash_account, revenue_account):
        _posted_cdv(main_branch, cash_account, revenue_account,
                    'capital_goods', 'V12CG', 5600, 600)
        p = build_vat_return_schedules(2025, 3)['input_schedule']
        row = next(r for r in p['rows'] if r['box'] == '18AB')
        assert row['base'] == Decimal('5000.00') and row['tax'] == Decimal('600.00')


class TestReconciliation:
    def test_in_balance_when_docs_equal_gl(
            self, db_session, main_branch, cash_account, revenue_account):
        _posted_crv(main_branch, cash_account, revenue_account,
                    'regular', 'V12', 11200, 1200)
        sched = build_vat_return_schedules(2025, 3)
        r = reconcile_vat_return(Decimal('1200.00'), Z, sched)
        assert r['output_docs'] == Decimal('1200.00')
        assert r['output_gl'] == Decimal('1200.00')
        assert r['in_balance'] is True

    def test_out_of_balance_when_gl_diverges(
            self, db_session, main_branch, cash_account, revenue_account):
        _posted_crv(main_branch, cash_account, revenue_account,
                    'regular', 'V12', 11200, 1200)
        sched = build_vat_return_schedules(2025, 3)
        r = reconcile_vat_return(Decimal('9999.00'), Z, sched)
        assert r['in_balance'] is False

    def test_gl_unavailable_is_never_in_balance(self, db_session, main_branch):
        sched = build_vat_return_schedules(2025, 3)
        r = reconcile_vat_return(None, None, sched)
        assert r['in_balance'] is False
        assert r['output_gl'] is None
