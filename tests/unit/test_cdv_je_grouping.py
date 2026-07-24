"""CDV JE sums same-account AP lines instead of one line per bill
(BUG-CRV-CDV-MULTI-LINE-SAME-ACCOUNT-NOT-SUMMED)."""
from decimal import Decimal
from datetime import date
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _account(code, name='Ctrl'):
    from app.accounts.models import Account
    a = Account(code=code, name=name, account_type='Liability', normal_balance='Credit', is_active=True)
    db.session.add(a); db.session.commit()
    return a


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='V-GRP', name='Grouping Test Vendor', is_active=True)
    db.session.add(v); db.session.commit()
    return v


def test_grouped_ap_lines_sums_same_account(db_session, main_branch, vendor):
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
    from app.cash_disbursements.views import _grouped_ap_lines

    ap_default = _account('9301', 'AP Default')
    cash_acct = _account('9391', 'Cash on Hand')
    bill1 = AccountsPayable(ap_number='APV-GRP-0001', ap_date=date(2026, 7, 1),
                            due_date=date(2026, 7, 31), vendor_id=vendor.id,
                            vendor_name=vendor.name, branch_id=main_branch.id, status='posted',
                            total_amount=Decimal('100.00'), balance=Decimal('100.00'), amount_paid=Decimal('0.00'))
    bill2 = AccountsPayable(ap_number='APV-GRP-0002', ap_date=date(2026, 7, 2),
                            due_date=date(2026, 8, 1), vendor_id=vendor.id,
                            vendor_name=vendor.name, branch_id=main_branch.id, status='posted',
                            total_amount=Decimal('50.00'), balance=Decimal('50.00'), amount_paid=Decimal('0.00'))
    db.session.add_all([bill1, bill2]); db.session.commit()

    cdv = CashDisbursementVoucher(cdv_number='CD-GRP-0001', cdv_date=date(2026, 7, 10),
                                  vendor_id=vendor.id, vendor_name=vendor.name,
                                  branch_id=main_branch.id, cash_account_id=cash_acct.id,
                                  status='draft')
    db.session.add(cdv); db.session.commit()
    cdv.ap_lines.append(CDVApLine(line_number=1, ap_id=bill1.id, ap_number=bill1.ap_number,
                                  original_balance=bill1.balance, amount_applied=Decimal('100.00')))
    cdv.ap_lines.append(CDVApLine(line_number=2, ap_id=bill2.id, ap_number=bill2.ap_number,
                                  original_balance=bill2.balance, amount_applied=Decimal('50.00')))
    db.session.commit()

    groups = _grouped_ap_lines(cdv, ap_default)
    assert len(groups) == 1   # both bills resolve to the same (default) AP account
    g = groups[0]
    assert g['account'].id == ap_default.id
    assert g['total'] == Decimal('150.00')
    assert g['refs'] == ['APV-GRP-0001', 'APV-GRP-0002']


def test_grouped_ap_lines_separates_different_accounts(db_session, main_branch, vendor):
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
    from app.cash_disbursements.views import _grouped_ap_lines

    ap_default = _account('9302', 'AP Default 2')
    ap_override = _account('9303', 'AP Override')
    cash_acct = _account('9391', 'Cash on Hand')
    bill1 = AccountsPayable(ap_number='APV-GRP-0003', ap_date=date(2026, 7, 1),
                            due_date=date(2026, 7, 31), vendor_id=vendor.id,
                            vendor_name=vendor.name, branch_id=main_branch.id, status='posted',
                            total_amount=Decimal('100.00'), balance=Decimal('100.00'), amount_paid=Decimal('0.00'),
                            ap_trade_account_id=ap_override.id)
    bill2 = AccountsPayable(ap_number='APV-GRP-0004', ap_date=date(2026, 7, 2),
                            due_date=date(2026, 8, 1), vendor_id=vendor.id,
                            vendor_name=vendor.name, branch_id=main_branch.id, status='posted',
                            total_amount=Decimal('50.00'), balance=Decimal('50.00'), amount_paid=Decimal('0.00'))
    db.session.add_all([bill1, bill2]); db.session.commit()

    cdv = CashDisbursementVoucher(cdv_number='CD-GRP-0002', cdv_date=date(2026, 7, 10),
                                  vendor_id=vendor.id, vendor_name=vendor.name,
                                  branch_id=main_branch.id, cash_account_id=cash_acct.id,
                                  status='draft')
    db.session.add(cdv); db.session.commit()
    cdv.ap_lines.append(CDVApLine(line_number=1, ap_id=bill1.id, ap_number=bill1.ap_number,
                                  original_balance=bill1.balance, amount_applied=Decimal('100.00')))
    cdv.ap_lines.append(CDVApLine(line_number=2, ap_id=bill2.id, ap_number=bill2.ap_number,
                                  original_balance=bill2.balance, amount_applied=Decimal('50.00')))
    db.session.commit()

    groups = _grouped_ap_lines(cdv, ap_default)
    assert len(groups) == 2
    accounts = {g['account'].id for g in groups}
    assert accounts == {ap_override.id, ap_default.id}
