"""CDVApLine settlement lines must inherit their AP-Trade account from the
specific AccountsPayable bill each line settles, not one shared CDV-level
account -- so a CDV settling two bills booked to different accounts posts
both correctly. See docs/superpowers/specs/2026-07-12-cd-cr-control-account-resolution-design.md."""
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.integration]


def _account(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _posted_bill(branch, vendor, ap_number, total, ap_trade_account_id):
    today = date.today()
    bill = AccountsPayable(
        ap_number=ap_number, vendor_id=vendor.id, vendor_name=vendor.name,
        payee_type='vendor', payee_id=vendor.id,
        branch_id=branch.id, ap_date=today, due_date=today,
        payment_terms='Net 30', status='posted',
        subtotal=total, total_before_wt=total,
        withholding_tax_rate=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=total, amount_paid=Decimal('0.00'), balance=total,
        ap_trade_account_id=ap_trade_account_id,
    )
    db.session.add(bill); db.session.commit()
    return bill


def test_cdv_settling_two_bills_credits_each_bills_own_account(
        db_session, accountant_user, main_branch):
    global_ap = _account('CDVS01', 'Global AP Trade', 'Liability', 'Credit')
    bill_a_acct = _account('CDVS02', 'Bill A AP Trade', 'Liability', 'Credit')
    bill_b_acct = _account('CDVS03', 'Bill B AP Trade', 'Liability', 'Credit')
    cash_acct = _account('CDVS04', 'Cash on Hand', 'Asset', 'Debit')
    assign_control_accounts(db_session, ap=global_ap.code)

    vendor = Vendor(code='CDVSV1', name='Settlement Test Vendor', is_active=True)
    db.session.add(vendor); db.session.commit()

    bill_a = _posted_bill(main_branch, vendor, 'CDVS-AP-A', Decimal('300.00'), bill_a_acct.id)
    bill_b = _posted_bill(main_branch, vendor, 'CDVS-AP-B', Decimal('700.00'), bill_b_acct.id)

    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id, cdv_number='CDVS-0001', cdv_date=date.today(),
        vendor_id=vendor.id, vendor_name=vendor.name, payment_method='cash',
        cash_account_id=cash_acct.id, notes='Settlement test', status='draft',
        total_ap_applied=Decimal('1000.00'), total_amount=Decimal('1000.00'),
    )
    db.session.add(cdv); db.session.flush()
    db.session.add(CDVApLine(cdv_id=cdv.id, line_number=1, ap_id=bill_a.id,
                             ap_number=bill_a.ap_number, original_balance=bill_a.balance,
                             amount_applied=Decimal('300.00')))
    db.session.add(CDVApLine(cdv_id=cdv.id, line_number=2, ap_id=bill_b.id,
                             ap_number=bill_b.ap_number, original_balance=bill_b.balance,
                             amount_applied=Decimal('700.00')))
    db.session.commit()
    db.session.refresh(cdv)

    from app.cash_disbursements.views import _post_cdv_je
    je = _post_cdv_je(cdv, accountant_user.id)
    db.session.commit()

    lines_a = [l for l in je.lines if l.account_id == bill_a_acct.id]
    lines_b = [l for l in je.lines if l.account_id == bill_b_acct.id]
    assert len(lines_a) == 1 and lines_a[0].debit_amount == Decimal('300.00')
    assert len(lines_b) == 1 and lines_b[0].debit_amount == Decimal('700.00')
    assert not any(l.account_id == global_ap.id for l in je.lines)


def test_draft_cdv_preview_shows_each_bills_own_account(db_session, accountant_user, main_branch):
    global_ap = _account('CDVS05', 'Global AP Trade 2', 'Liability', 'Credit')
    bill_acct = _account('CDVS06', 'Bill Own Account', 'Liability', 'Credit')
    cash_acct = _account('CDVS07', 'Cash on Hand 2', 'Asset', 'Debit')
    assign_control_accounts(db_session, ap=global_ap.code)

    vendor = Vendor(code='CDVSV2', name='Preview Test Vendor', is_active=True)
    db.session.add(vendor); db.session.commit()
    bill = _posted_bill(main_branch, vendor, 'CDVS-AP-C', Decimal('400.00'), bill_acct.id)

    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id, cdv_number='CDVS-0002', cdv_date=date.today(),
        vendor_id=vendor.id, vendor_name=vendor.name, payment_method='cash',
        cash_account_id=cash_acct.id, notes='Preview test', status='draft',
        total_ap_applied=Decimal('400.00'), total_amount=Decimal('400.00'),
    )
    db.session.add(cdv); db.session.flush()
    db.session.add(CDVApLine(cdv_id=cdv.id, line_number=1, ap_id=bill.id,
                             ap_number=bill.ap_number, original_balance=bill.balance,
                             amount_applied=Decimal('400.00')))
    db.session.commit()
    db.session.refresh(cdv)

    from app.cash_disbursements.views import _build_cdv_je_preview
    preview = _build_cdv_je_preview(cdv)  # cdv.journal_entry is None -> inline preview path
    codes = {row['code'] for row in preview}
    assert bill_acct.code in codes
    assert global_ap.code not in codes
