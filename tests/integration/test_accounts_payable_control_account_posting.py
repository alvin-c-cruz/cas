import pytest
from decimal import Decimal
from datetime import date
from app import db
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.withholding_tax.models import WithholdingTax
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def _account(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def test_post_ap_uses_document_ap_trade_override_not_global(
        db_session, accountant_user, main_branch):
    global_ap = _account('APCP01', 'Global AP Trade', 'Liability', 'Credit')
    override_ap = _account('APCP02', 'Override AP Trade', 'Liability', 'Credit')
    expense = _account('APCP03', 'Expense', 'Expense', 'Debit')
    assign_control_accounts(db_session, ap=global_ap.code)

    vendor = Vendor(code='APCPV1', name='Posting Field Vendor', is_active=True)
    db.session.add(vendor); db.session.commit()

    ap = AccountsPayable(
        branch_id=main_branch.id, ap_number='APCP-0001',
        ap_date=date.today(), due_date=date.today(),
        payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id, vendor_name=vendor.name,
        status='draft', ap_trade_account_id=override_ap.id,
        subtotal=Decimal('500.00'), total_amount=Decimal('500.00'),
    )
    db.session.add(ap); db.session.commit()
    item = AccountsPayableItem(ap_id=ap.id, line_number=1, description='Supplies',
                              account_id=expense.id, line_total=Decimal('500.00'),
                              vat_amount=Decimal('0.00'))
    db.session.add(item); db.session.commit()
    db.session.refresh(ap)

    from app.accounts_payable.views import _post_ap_je
    je = _post_ap_je(ap, accountant_user.id)
    db.session.commit()

    ap_lines = [l for l in je.lines if l.account_id == override_ap.id]
    assert len(ap_lines) == 1
    assert ap_lines[0].credit_amount == Decimal('500.00')
    assert not any(l.account_id == global_ap.id for l in je.lines)


def test_post_ap_uses_document_wht_payable_override_not_global(
        db_session, accountant_user, main_branch):
    ap_acct = _account('APCP04', 'AP Trade', 'Liability', 'Credit')
    global_wht = _account('APCP05', 'Global WHT Payable', 'Liability', 'Credit')
    override_wht = _account('APCP06', 'Override WHT Payable', 'Liability', 'Credit')
    expense = _account('APCP07', 'Expense', 'Expense', 'Debit')
    assign_control_accounts(db_session, wht_payable=global_wht.code)

    # ATC with NO per-code payable_account, so _wht_payable_buckets falls back
    # to the fallback_acct argument that _post_ap_je now resolves from
    # ap.wht_payable_account (not the ATC's own payable_account).
    atc = WithholdingTax(code='APCPW1', name='Expanded 2%', rate=Decimal('2.00'),
                         is_active=True, tax_type='expanded')
    db.session.add(atc); db.session.commit()
    assert atc.payable_account_id is None

    vendor = Vendor(code='APCPV2', name='WHT Override Vendor', is_active=True)
    db.session.add(vendor); db.session.commit()

    ap = AccountsPayable(
        branch_id=main_branch.id, ap_number='APCP-0002',
        ap_date=date.today(), due_date=date.today(),
        payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id, vendor_name=vendor.name,
        status='draft', ap_trade_account_id=ap_acct.id,
        wht_payable_account_id=override_wht.id,
        subtotal=Decimal('1000.00'), withholding_tax_amount=Decimal('20.00'),
        total_amount=Decimal('980.00'),
    )
    db.session.add(ap); db.session.commit()
    item = AccountsPayableItem(ap_id=ap.id, line_number=1, description='Supplies',
                              account_id=expense.id, line_total=Decimal('1000.00'),
                              vat_amount=Decimal('0.00'), wt_id=atc.id,
                              wt_rate=Decimal('2.00'), wt_amount=Decimal('20.00'))
    db.session.add(item); db.session.commit()
    db.session.refresh(ap)

    from app.accounts_payable.views import _post_ap_je
    je = _post_ap_je(ap, accountant_user.id)
    db.session.commit()

    wht_lines = [l for l in je.lines if l.account_id == override_wht.id]
    assert len(wht_lines) == 1
    assert wht_lines[0].credit_amount == Decimal('20.00')
    assert not any(l.account_id == global_wht.id for l in je.lines)


def test_preview_uses_document_ap_trade_and_wht_payable_overrides_not_global(
        db_session, accountant_user, main_branch):
    global_ap = _account('APCP08', 'Global AP Trade', 'Liability', 'Credit')
    override_ap = _account('APCP09', 'Override AP Trade', 'Liability', 'Credit')
    global_wht = _account('APCP10', 'Global WHT Payable', 'Liability', 'Credit')
    override_wht = _account('APCP11', 'Override WHT Payable', 'Liability', 'Credit')
    expense = _account('APCP12', 'Expense', 'Expense', 'Debit')
    assign_control_accounts(db_session, ap=global_ap.code, wht_payable=global_wht.code)

    atc = WithholdingTax(code='APCPW2', name='Expanded 2%', rate=Decimal('2.00'),
                         is_active=True, tax_type='expanded')
    db.session.add(atc); db.session.commit()
    assert atc.payable_account_id is None

    vendor = Vendor(code='APCPV3', name='Preview Override Vendor', is_active=True)
    db.session.add(vendor); db.session.commit()

    # DRAFT AP with no stored journal_entry yet -> _build_je_preview takes the
    # inline-compute path, which must read the bill's own override accounts
    # rather than the global control-account settings.
    ap = AccountsPayable(
        branch_id=main_branch.id, ap_number='APCP-0003',
        ap_date=date.today(), due_date=date.today(),
        payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id, vendor_name=vendor.name,
        status='draft', ap_trade_account_id=override_ap.id,
        wht_payable_account_id=override_wht.id,
        subtotal=Decimal('1000.00'), withholding_tax_amount=Decimal('20.00'),
        total_amount=Decimal('980.00'),
    )
    db.session.add(ap); db.session.commit()
    item = AccountsPayableItem(ap_id=ap.id, line_number=1, description='Supplies',
                              account_id=expense.id, line_total=Decimal('1000.00'),
                              vat_amount=Decimal('0.00'), wt_id=atc.id,
                              wt_rate=Decimal('2.00'), wt_amount=Decimal('20.00'))
    db.session.add(item); db.session.commit()
    db.session.refresh(ap)

    assert ap.journal_entry is None

    from app.accounts_payable.views import _build_je_preview
    preview = _build_je_preview(ap)

    codes = {row['code'] for row in preview}
    assert override_ap.code in codes
    assert override_wht.code in codes
    assert global_ap.code not in codes
    assert global_wht.code not in codes
