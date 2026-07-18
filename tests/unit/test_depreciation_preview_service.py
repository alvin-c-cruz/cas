from datetime import date
from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.fixed_assets.models import FixedAsset
from app.fixed_asset_depreciation.service import compute_depreciation_preview
# FixedAsset.accumulated_depreciation lazily imports DepreciationRun/DepreciationEntry
# at call time -- until Task 8 wires app/__init__.py's eager model imports, this test
# file must import them itself at module level so the session-scoped schema fixture
# (_db_schema in conftest.py) sees these tables before its one-time create_all().
from app.fixed_asset_depreciation.models import DepreciationRun, DepreciationEntry  # noqa: F401


def _asset(db_session, main_branch, code, acquisition_date, cost=Decimal('60000.00'),
          useful_life_months=60, salvage_value=Decimal('0'), method='straight_line',
          status='active', declining_balance_rate=None, total_estimated_units=None,
          opening_accumulated_depreciation=Decimal('0')):
    cost_acct = Account(code=f'174{code[-2:]}1', name=f'{code} Cost', account_type='Asset',
                        normal_balance='Debit')
    accum_acct = Account(code=f'174{code[-2:]}2', name=f'{code} Accum', account_type='Asset',
                         normal_balance='Credit')
    exp_acct = Account(code=f'607{code[-2:]}', name=f'{code} Dep Exp', account_type='Expense',
                       normal_balance='Debit')
    db_session.add_all([cost_acct, accum_acct, exp_acct])
    db_session.commit()
    asset = FixedAsset(
        branch_id=main_branch.id, code=code, name=code,
        acquisition_source_type='opening', acquisition_source_id=None,
        acquisition_source_line_id=None, acquisition_date=acquisition_date,
        acquisition_cost=cost, cost_account_id=cost_acct.id,
        accumulated_depreciation_account_id=accum_acct.id,
        depreciation_expense_account_id=exp_acct.id, depreciation_method=method,
        useful_life_months=useful_life_months, declining_balance_rate=declining_balance_rate,
        total_estimated_units=total_estimated_units, salvage_value=salvage_value,
        opening_accumulated_depreciation=opening_accumulated_depreciation, status=status,
        created_by_id=1,
    )
    db_session.add(asset)
    db_session.commit()
    return asset


def test_active_asset_included_with_computed_amount(db_session, main_branch):
    _asset(db_session, main_branch, 'FA-P01', date(2024, 1, 1))
    rows = compute_depreciation_preview(main_branch.id, 2026, 6)
    assert len(rows) == 1
    assert rows[0]['depreciation_amount'] == Decimal('1000.00')  # 60000/60


def test_asset_not_yet_acquired_is_excluded_entirely(db_session, main_branch):
    _asset(db_session, main_branch, 'FA-P02', date(2027, 1, 1))  # future
    rows = compute_depreciation_preview(main_branch.id, 2026, 6)
    assert rows == []


def test_disposed_asset_is_excluded_entirely(db_session, main_branch):
    _asset(db_session, main_branch, 'FA-P03', date(2024, 1, 1), status='disposed')
    rows = compute_depreciation_preview(main_branch.id, 2026, 6)
    assert rows == []


def test_fully_depreciated_active_asset_shown_at_zero_not_hidden(db_session, main_branch):
    _asset(db_session, main_branch, 'FA-P04', date(2020, 1, 1), cost=Decimal('12000.00'),
          useful_life_months=12, opening_accumulated_depreciation=Decimal('12000.00'))
    rows = compute_depreciation_preview(main_branch.id, 2026, 6)
    assert len(rows) == 1
    assert rows[0]['depreciation_amount'] == Decimal('0.00')


def test_units_of_production_flags_needs_units_input_and_uses_supplied_value(db_session,
                                                                              main_branch):
    asset = _asset(db_session, main_branch, 'FA-P05', date(2024, 1, 1), cost=Decimal('50000.00'),
                   method='units_of_production', total_estimated_units=Decimal('10000'))
    rows_no_input = compute_depreciation_preview(main_branch.id, 2026, 6)
    assert rows_no_input[0]['needs_units_input'] is True
    assert rows_no_input[0]['depreciation_amount'] == Decimal('0.00')

    rows_with_input = compute_depreciation_preview(
        main_branch.id, 2026, 6, units_used_by_asset={asset.id: Decimal('500')})
    assert rows_with_input[0]['depreciation_amount'] == Decimal('2500.00')  # 5.00/unit * 500


def test_branch_scoping_excludes_other_branches(db_session, main_branch, branch_manila):
    _asset(db_session, branch_manila, 'FA-P06', date(2024, 1, 1))
    rows = compute_depreciation_preview(main_branch.id, 2026, 6)
    assert rows == []


def test_accumulated_after_and_net_book_value_after_are_consistent(db_session, main_branch):
    _asset(db_session, main_branch, 'FA-P07', date(2024, 1, 1), cost=Decimal('60000.00'),
          useful_life_months=60)
    rows = compute_depreciation_preview(main_branch.id, 2026, 6)
    row = rows[0]
    assert row['accumulated_after'] == row['prior_accumulated'] + row['depreciation_amount']
    assert row['net_book_value_after'] == Decimal('60000.00') - row['accumulated_after']
