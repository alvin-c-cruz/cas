import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.reports.bir import get_alphalist_of_payees, count_excluded_final_tax

pytestmark = [pytest.mark.unit]


def _wt(code, rate, tax_type='expanded'):
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code=code, name=code, rate=Decimal(str(rate)), tax_type=tax_type)
    db.session.add(wt); db.session.commit()
    return wt


def _vendor(code):
    from app.vendors.models import Vendor
    v = Vendor(code=code, name=f'Vendor {code}', tin='001-002-003-000', address='9 Ayala Ave')
    db.session.add(v); db.session.commit()
    return v


def _posted_cdv_wht(branch, cash_acct, exp_acct, vendor, wt, amount, wt_amount,
                    when=date(2025, 8, 10)):
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    cdv = CashDisbursementVoucher(
        branch_id=branch.id, cdv_number=f'CDV-{vendor.code}', cdv_date=when,
        vendor_id=vendor.id, vendor_name=vendor.name, vendor_tin=vendor.tin,
        cash_account_id=cash_acct.id, status='posted')
    cdv.expense_lines.append(CDVExpenseLine(
        line_number=1, description='svc', amount=Decimal(str(amount)),
        vat_rate=Decimal('0'), vat_amount=Decimal('0.00'),
        line_total=Decimal(str(amount)), wt_id=wt.id, wt_rate=wt.rate,
        wt_amount=Decimal(str(wt_amount)), account_id=exp_acct.id))
    db.session.add(cdv); db.session.commit()
    return cdv


def test_cdv_vendor_appears_in_alphalist(db_session, main_branch, cash_account, revenue_account):
    wt = _wt('WC158', 2)
    v = _vendor('CDVONLY')
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, wt, 10000, 200)
    rows = get_alphalist_of_payees(2025, 3)
    names = [r['payee_name'] for r in rows]
    assert 'Vendor CDVONLY' in names          # was invisible before (AP-only query)
    row = next(r for r in rows if r['payee_name'] == 'Vendor CDVONLY')
    assert row['tax_withheld'] == Decimal('200.00')
    assert row['payee_address'] == '9 Ayala Ave'   # address joined in reporting layer
    assert row['gross_income'] == Decimal('10000.00')  # net of (zero) VAT here


def test_final_tax_excluded_and_counted(db_session, main_branch, cash_account, revenue_account):
    fwt = _wt('WI999', 15, tax_type='final')
    v = _vendor('FINAL')
    _posted_cdv_wht(main_branch, cash_account, revenue_account, v, fwt, 10000, 1500)
    rows = get_alphalist_of_payees(2025, 3)
    assert all(r['payee_name'] != 'Vendor FINAL' for r in rows)   # excluded by query
    adv = count_excluded_final_tax(2025, 3, side='payor')
    assert adv['count'] == 1 and adv['total'] == Decimal('1500.00')


def test_alphalist_has_total_row_when_nonempty(db_session, main_branch, cash_account, revenue_account):
    wt = _wt('WC158', 2)
    _posted_cdv_wht(main_branch, cash_account, revenue_account, _vendor('A'), wt, 10000, 200)
    rows = get_alphalist_of_payees(2025, 3)
    assert rows[-1]['payee_name'] == 'TOTAL'
    assert rows[-1]['tax_withheld'] == Decimal('200.00')
