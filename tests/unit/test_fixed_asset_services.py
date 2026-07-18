from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.vendors.models import Vendor
from app.fixed_assets.models import FixedAsset
from app.fixed_assets.services import (
    FixedAssetTagError, get_taggable_line, get_tag_for_line, get_tags_for_document,
    leaf_accounts_by_type, create_fixed_asset,
)


def _posted_ap_with_line(db_session, main_branch, account):
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-2026-01-0001',
                         ap_date=date(2026, 1, 10), due_date=date(2026, 2, 10),
                         vendor_name='Test Vendor', status='posted')
    db_session.add(ap)
    db_session.flush()
    item = AccountsPayableItem(ap_id=ap.id, line_number=1, description='Laptop',
                               amount=Decimal('50000.00'), line_total=Decimal('50000.00'),
                               account_id=account.id)
    db_session.add(item)
    db_session.commit()
    return ap, item


def test_get_taggable_line_ap_posted(db_session, main_branch):
    acct = Account(code='17301', name='Office Equipment', account_type='Asset',
                   normal_balance='Debit')
    db_session.add(acct)
    db_session.commit()
    ap, item = _posted_ap_with_line(db_session, main_branch, acct)

    line, cost_account_id, amount = get_taggable_line('ap_bill', ap.id, item.id)
    assert line is item
    assert cost_account_id == acct.id
    assert amount == Decimal('50000.00')


def test_get_taggable_line_rejects_draft(db_session, main_branch):
    acct = Account(code='17301', name='Office Equipment', account_type='Asset',
                   normal_balance='Debit')
    db_session.add(acct)
    db_session.commit()
    ap, item = _posted_ap_with_line(db_session, main_branch, acct)
    ap.status = 'draft'
    db_session.commit()

    with pytest.raises(FixedAssetTagError):
        get_taggable_line('ap_bill', ap.id, item.id)


def test_get_taggable_line_rejects_already_tagged(db_session, main_branch):
    acct = Account(code='17301', name='Office Equipment', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17302', name='Accum Dep', account_type='Asset',
                    normal_balance='Debit')
    exp = Account(code='60501', name='Dep Expense', account_type='Expense',
                  normal_balance='Debit')
    db_session.add_all([acct, accum, exp])
    db_session.commit()
    ap, item = _posted_ap_with_line(db_session, main_branch, acct)

    create_fixed_asset(
        branch_id=main_branch.id, code='FA-0001', name='Laptop', category_id=None,
        acquisition_source_type='ap_bill', acquisition_source_id=ap.id,
        acquisition_source_line_id=item.id, acquisition_date=date(2026, 1, 10),
        acquisition_cost=Decimal('50000.00'), cost_account_id=acct.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=36, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )

    with pytest.raises(FixedAssetTagError):
        get_taggable_line('ap_bill', ap.id, item.id)


def _posted_cdv_with_line(db_session, main_branch, account):
    vendor = Vendor(code='V001', name='Test Vendor', is_active=True)
    cash_account = Account(code='10101', name='Cash on Hand', account_type='Asset',
                           normal_balance='Debit')
    db_session.add_all([vendor, cash_account])
    db_session.flush()
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id, cdv_number='CD-2026-01-0001',
        cdv_date=date(2026, 1, 10), vendor_id=vendor.id, vendor_name=vendor.name,
        payment_method='cash', cash_account_id=cash_account.id, notes='Test',
        status='posted', total_ap_applied=Decimal('0.00'), total_expense=Decimal('50000.00'),
        total_vat=Decimal('0.00'), total_wt=Decimal('0.00'), total_amount=Decimal('50000.00'),
    )
    db_session.add(cdv)
    db_session.flush()
    line = CDVExpenseLine(cdv_id=cdv.id, line_number=1, description='Laptop',
                          amount=Decimal('50000.00'), line_total=Decimal('50000.00'),
                          account_id=account.id)
    db_session.add(line)
    db_session.commit()
    return cdv, line


def _posted_jv_with_lines(db_session, main_branch, debit_account, credit_account):
    entry = JournalEntry(
        entry_number='JE-0001', entry_date=date(2026, 1, 10),
        description='Test JV', entry_type='adjustment', status='posted',
        branch_id=main_branch.id, total_debit=Decimal('50000.00'),
        total_credit=Decimal('50000.00'), is_balanced=True,
    )
    db_session.add(entry)
    db_session.flush()
    debit_line = JournalEntryLine(entry_id=entry.id, line_number=1,
                                  account_id=debit_account.id, description='Laptop',
                                  debit_amount=Decimal('50000.00'), credit_amount=Decimal('0.00'))
    credit_line = JournalEntryLine(entry_id=entry.id, line_number=2,
                                   account_id=credit_account.id, description='Cash out',
                                   debit_amount=Decimal('0.00'), credit_amount=Decimal('50000.00'))
    db_session.add_all([debit_line, credit_line])
    db_session.commit()
    return entry, debit_line, credit_line


def test_get_taggable_line_cdv_posted(db_session, main_branch):
    acct = Account(code='17301', name='Office Equipment', account_type='Asset',
                   normal_balance='Debit')
    db_session.add(acct)
    db_session.commit()
    cdv, line = _posted_cdv_with_line(db_session, main_branch, acct)

    result_line, cost_account_id, amount = get_taggable_line('cdv', cdv.id, line.id)
    assert result_line is line
    assert cost_account_id == acct.id
    assert amount == Decimal('50000.00')


def test_get_taggable_line_jv_posted_debit_line(db_session, main_branch):
    debit_acct = Account(code='17301', name='Office Equipment', account_type='Asset',
                         normal_balance='Debit')
    credit_acct = Account(code='10101', name='Cash on Hand', account_type='Asset',
                          normal_balance='Debit')
    db_session.add_all([debit_acct, credit_acct])
    db_session.commit()
    entry, debit_line, credit_line = _posted_jv_with_lines(
        db_session, main_branch, debit_acct, credit_acct)

    result_line, cost_account_id, amount = get_taggable_line('jv', entry.id, debit_line.id)
    assert result_line is debit_line
    assert cost_account_id == debit_acct.id
    assert amount == Decimal('50000.00')


def test_get_taggable_line_jv_rejects_credit_line(db_session, main_branch):
    debit_acct = Account(code='17301', name='Office Equipment', account_type='Asset',
                         normal_balance='Debit')
    credit_acct = Account(code='10101', name='Cash on Hand', account_type='Asset',
                          normal_balance='Debit')
    db_session.add_all([debit_acct, credit_acct])
    db_session.commit()
    entry, debit_line, credit_line = _posted_jv_with_lines(
        db_session, main_branch, debit_acct, credit_acct)

    with pytest.raises(FixedAssetTagError):
        get_taggable_line('jv', entry.id, credit_line.id)


def test_get_taggable_line_rejects_nonexistent_line(db_session, main_branch):
    acct = Account(code='17301', name='Office Equipment', account_type='Asset',
                   normal_balance='Debit')
    db_session.add(acct)
    db_session.commit()
    ap, item = _posted_ap_with_line(db_session, main_branch, acct)

    with pytest.raises(FixedAssetTagError):
        get_taggable_line('ap_bill', ap.id, 999999)


def test_get_tags_for_document_and_cancel_guard(db_session, main_branch):
    acct = Account(code='17301', name='Office Equipment', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17302', name='Accum Dep', account_type='Asset',
                    normal_balance='Debit')
    exp = Account(code='60501', name='Dep Expense', account_type='Expense',
                  normal_balance='Debit')
    db_session.add_all([acct, accum, exp])
    db_session.commit()
    ap, item = _posted_ap_with_line(db_session, main_branch, acct)

    assert get_tags_for_document('ap_bill', ap.id) == []

    asset = create_fixed_asset(
        branch_id=main_branch.id, code='FA-0001', name='Laptop', category_id=None,
        acquisition_source_type='ap_bill', acquisition_source_id=ap.id,
        acquisition_source_line_id=item.id, acquisition_date=date(2026, 1, 10),
        acquisition_cost=Decimal('50000.00'), cost_account_id=acct.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=36, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )

    tagged = get_tags_for_document('ap_bill', ap.id)
    assert tagged == [asset]
    assert get_tag_for_line('ap_bill', ap.id, item.id) == asset
    assert get_tag_for_line('ap_bill', ap.id, 999) is None


def test_leaf_accounts_by_type_excludes_parents(db_session):
    parent = Account(code='170', name='Fixed Assets', account_type='Asset',
                     normal_balance='Debit')
    db_session.add(parent)
    db_session.commit()
    child = Account(code='17301', name='Office Equipment', account_type='Asset',
                    normal_balance='Debit', parent_id=parent.id)
    other_type = Account(code='60501', name='Dep Expense', account_type='Expense',
                         normal_balance='Debit')
    db_session.add_all([child, other_type])
    db_session.commit()

    leaves = leaf_accounts_by_type('Asset')
    codes = {a.code for a in leaves}
    assert '17301' in codes
    assert '170' not in codes    # parent excluded
    assert '60501' not in codes  # wrong type excluded


def test_leaf_accounts_by_type_excludes_childless_top_level_account(db_session):
    """A freshly-created top-level (parent_id is None) account with no children
    yet is still a non-postable PARENT/header by CAS's hierarchy rule (a node is
    a header if it is top-level OR has children). Regression for the bug where
    leaf_accounts_by_type only checked 'has no children' (id not in parent_ids)
    and never checked parent_id -- a childless top-level account has nothing
    pointing to it as a parent, so the old code wrongly included it as postable."""
    top_level = Account(code='170', name='Fixed Assets', account_type='Asset',
                        normal_balance='Debit')
    db_session.add(top_level)
    db_session.commit()

    leaves = leaf_accounts_by_type('Asset')
    codes = {a.code for a in leaves}
    assert '170' not in codes
