from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.accounts.models import Account
from app.fixed_assets.models import FixedAsset
from app.fixed_asset_depreciation.models import DepreciationRun, DepreciationEntry
from app.fixed_asset_depreciation.service import post_depreciation_run
from app.journal_entries.models import JournalEntry
from app.audit.models import AuditLog


def _asset(db_session, main_branch, code='FA-PR01', cost=Decimal('60000.00'),
          useful_life_months=60, cost_code='17601', accum_code='17602', exp_code='60801'):
    cost_acct = Account(code=cost_code, name='Cost', account_type='Asset', normal_balance='Debit')
    accum_acct = Account(code=accum_code, name='Accum', account_type='Asset',
                         normal_balance='Credit')
    exp_acct = Account(code=exp_code, name='Dep Exp', account_type='Expense',
                       normal_balance='Debit')
    db_session.add_all([cost_acct, accum_acct, exp_acct])
    db_session.commit()
    asset = FixedAsset(
        branch_id=main_branch.id, code=code, name=code, acquisition_source_type='opening',
        acquisition_source_id=None, acquisition_source_line_id=None,
        acquisition_date=date(2024, 1, 1), acquisition_cost=cost, cost_account_id=cost_acct.id,
        accumulated_depreciation_account_id=accum_acct.id,
        depreciation_expense_account_id=exp_acct.id, depreciation_method='straight_line',
        useful_life_months=useful_life_months, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )
    db_session.add(asset)
    db_session.commit()
    return asset, cost_acct, accum_acct, exp_acct


def test_post_creates_run_entries_and_balanced_je(db_session, main_branch, admin_user):
    asset, cost_acct, accum_acct, exp_acct = _asset(db_session, main_branch)
    run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)

    assert run.status == 'posted'
    assert run.journal_entry_id is not None
    entries = DepreciationEntry.query.filter_by(run_id=run.id).all()
    assert len(entries) == 1
    assert entries[0].fixed_asset_id == asset.id
    assert entries[0].depreciation_amount == Decimal('1000.00')

    je = db.session.get(JournalEntry, run.journal_entry_id)
    assert je.status == 'posted'
    assert je.is_balanced
    assert je.total_debit == Decimal('1000.00')
    assert je.total_credit == Decimal('1000.00')
    lines = je.lines.all()
    assert len(lines) == 2
    dr_line = next(l for l in lines if l.debit_amount > 0)
    cr_line = next(l for l in lines if l.credit_amount > 0)
    assert dr_line.account_id == exp_acct.id
    assert cr_line.account_id == accum_acct.id

    log = AuditLog.query.filter_by(module='fixed_asset_depreciation', action='create',
                                    record_id=run.id).first()
    assert log is not None


def test_je_lines_are_grouped_by_account_across_multiple_assets(db_session, main_branch,
                                                                  admin_user):
    """Two assets sharing the SAME expense/accum-dep accounts must produce ONE
    Dr line and ONE Cr line summing both, not one line pair per asset."""
    asset1, cost1, accum1, exp1 = _asset(db_session, main_branch, code='FA-PR10',
                                         cost=Decimal('12000.00'), useful_life_months=12,
                                         cost_code='17611', accum_code='17612', exp_code='60811')
    asset2 = FixedAsset(
        branch_id=main_branch.id, code='FA-PR11', name='FA-PR11',
        acquisition_source_type='opening', acquisition_source_id=None,
        acquisition_source_line_id=None, acquisition_date=date(2024, 1, 1),
        acquisition_cost=Decimal('24000.00'), cost_account_id=cost1.id,
        accumulated_depreciation_account_id=accum1.id, depreciation_expense_account_id=exp1.id,
        depreciation_method='straight_line', useful_life_months=12, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )
    db_session.add(asset2)
    db_session.commit()

    run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    je = db.session.get(JournalEntry, run.journal_entry_id)
    lines = je.lines.all()
    assert len(lines) == 2  # NOT 4
    dr_line = next(l for l in lines if l.debit_amount > 0)
    assert dr_line.debit_amount == Decimal('1000.00') + Decimal('2000.00')  # 12000/12 + 24000/12


def test_second_post_for_same_branch_period_rejected(db_session, main_branch, admin_user):
    _asset(db_session, main_branch)
    post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    with pytest.raises(ValueError, match='already exists'):
        post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)


def test_zero_amount_run_creates_run_row_with_no_je(db_session, main_branch, admin_user):
    """Every asset already fully depreciated -- the run row still gets
    created (occupying the period slot, matching what was previewed), but no
    JE is posted since there's nothing to post."""
    _asset(db_session, main_branch, cost=Decimal('12000.00'), useful_life_months=12)
    fa = FixedAsset.query.filter_by(branch_id=main_branch.id).first()
    fa.opening_accumulated_depreciation = Decimal('12000.00')
    db_session.commit()

    run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    assert run.status == 'posted'
    assert run.journal_entry_id is None
