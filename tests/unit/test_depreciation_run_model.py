from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from app import db
from app.fixed_asset_depreciation.models import DepreciationRun, DepreciationEntry
from app.fixed_assets.models import FixedAsset
from app.accounts.models import Account


def _asset(db_session, main_branch, code='FA-D001'):
    cost = Account(code='17401', name='Machinery - Cost', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17402', name='Machinery - Accum. Dep.', account_type='Asset',
                    normal_balance='Credit')
    exp = Account(code='60601', name='Depreciation Expense', account_type='Expense',
                  normal_balance='Debit')
    db_session.add_all([cost, accum, exp])
    db_session.commit()
    asset = FixedAsset(
        branch_id=main_branch.id, code=code, name='Lathe Machine',
        acquisition_source_type='opening', acquisition_source_id=None,
        acquisition_source_line_id=None, acquisition_date=date(2024, 1, 15),
        acquisition_cost=Decimal('120000.00'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=60, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )
    db_session.add(asset)
    db_session.commit()
    return asset


def test_depreciation_run_to_dict(db_session, main_branch):
    asset = _asset(db_session, main_branch)
    run = DepreciationRun(branch_id=main_branch.id, period_year=2026, period_month=1,
                          status='posted', created_by_id=1)
    db_session.add(run)
    db_session.commit()
    entry = DepreciationEntry(run_id=run.id, fixed_asset_id=asset.id,
                              depreciation_amount=Decimal('2000.00'),
                              accumulated_depreciation_after=Decimal('2000.00'),
                              net_book_value_after=Decimal('118000.00'))
    db_session.add(entry)
    db_session.commit()

    d = run.to_dict()
    assert d['branch_id'] == main_branch.id
    assert d['period_year'] == 2026
    assert d['period_month'] == 1
    assert d['status'] == 'posted'

    ed = entry.to_dict()
    assert ed['depreciation_amount'] == 2000.00
    assert ed['fixed_asset_id'] == asset.id


def test_second_live_run_for_same_branch_period_rejected(db_session, main_branch):
    db_session.add(DepreciationRun(branch_id=main_branch.id, period_year=2026, period_month=2,
                                   status='posted', created_by_id=1))
    db_session.commit()
    db_session.add(DepreciationRun(branch_id=main_branch.id, period_year=2026, period_month=2,
                                   status='draft', created_by_id=1))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_reversed_run_frees_the_period_slot(db_session, main_branch):
    """A 'reversed' run does not collide with a new run for the same branch/period --
    this is what lets an accountant correct a mistake by reversing then re-running."""
    r1 = DepreciationRun(branch_id=main_branch.id, period_year=2026, period_month=3,
                         status='posted', created_by_id=1)
    db_session.add(r1)
    db_session.commit()
    r1.status = 'reversed'
    db_session.commit()

    db_session.add(DepreciationRun(branch_id=main_branch.id, period_year=2026, period_month=3,
                                   status='posted', created_by_id=1))
    db_session.commit()  # must NOT raise
    assert DepreciationRun.query.filter_by(branch_id=main_branch.id, period_year=2026,
                                            period_month=3).count() == 2
