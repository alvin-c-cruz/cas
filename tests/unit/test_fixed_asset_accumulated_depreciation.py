from datetime import date
from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.fixed_assets.models import FixedAsset
from app.fixed_asset_depreciation.models import DepreciationRun, DepreciationEntry


def _asset_with_opening(db_session, main_branch, opening=Decimal('5000.00')):
    cost = Account(code='17501', name='Equipment - Cost', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17502', name='Equipment - Accum. Dep.', account_type='Asset',
                    normal_balance='Credit')
    exp = Account(code='60701', name='Depreciation Expense', account_type='Expense',
                  normal_balance='Debit')
    db_session.add_all([cost, accum, exp])
    db_session.commit()
    asset = FixedAsset(
        branch_id=main_branch.id, code='FA-ACC-001', name='Test Asset',
        acquisition_source_type='opening', acquisition_source_id=None,
        acquisition_source_line_id=None, acquisition_date=date(2023, 1, 1),
        acquisition_cost=Decimal('60000.00'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=60, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=opening, created_by_id=1,
    )
    db_session.add(asset)
    db_session.commit()
    return asset


def test_accumulated_depreciation_is_opening_only_with_no_posted_runs(db_session, main_branch):
    asset = _asset_with_opening(db_session, main_branch, Decimal('5000.00'))
    assert asset.accumulated_depreciation == Decimal('5000.00')


def test_accumulated_depreciation_sums_posted_entries_on_top_of_opening(db_session, main_branch):
    asset = _asset_with_opening(db_session, main_branch, Decimal('5000.00'))
    run = DepreciationRun(branch_id=main_branch.id, period_year=2026, period_month=1,
                          status='posted', created_by_id=1)
    db_session.add(run)
    db_session.commit()
    db_session.add(DepreciationEntry(run_id=run.id, fixed_asset_id=asset.id,
                                     depreciation_amount=Decimal('1000.00'),
                                     accumulated_depreciation_after=Decimal('6000.00'),
                                     net_book_value_after=Decimal('54000.00')))
    db_session.commit()
    db_session.refresh(asset)
    assert asset.accumulated_depreciation == Decimal('6000.00')  # 5000 opening + 1000 posted


def test_accumulated_depreciation_excludes_entries_from_reversed_runs(db_session, main_branch):
    """A reversed run's entries must NOT count -- the whole point of reversing is that
    the period's depreciation never happened from the books' perspective."""
    asset = _asset_with_opening(db_session, main_branch, Decimal('0'))
    run = DepreciationRun(branch_id=main_branch.id, period_year=2026, period_month=1,
                          status='reversed', created_by_id=1)
    db_session.add(run)
    db_session.commit()
    db_session.add(DepreciationEntry(run_id=run.id, fixed_asset_id=asset.id,
                                     depreciation_amount=Decimal('1000.00'),
                                     accumulated_depreciation_after=Decimal('1000.00'),
                                     net_book_value_after=Decimal('59000.00')))
    db_session.commit()
    db_session.refresh(asset)
    assert asset.accumulated_depreciation == Decimal('0')
