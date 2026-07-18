from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from app import db
from app.fixed_assets.models import FixedAsset
from app.accounts.models import Account
from app.branches.models import Branch


def _accounts(db_session):
    cost = Account(code='17301', name='Office Equipment - Cost', account_type='Asset',
                    normal_balance='Debit')
    accum = Account(code='17302', name='Office Equipment - Accum. Dep.', account_type='Asset',
                     normal_balance='Credit')
    exp = Account(code='60501', name='Depreciation Expense', account_type='Expense',
                  normal_balance='Debit')
    db_session.add_all([cost, accum, exp])
    db_session.commit()
    return cost, accum, exp


def test_fixed_asset_to_dict(db_session, main_branch):
    cost, accum, exp = _accounts(db_session)
    asset = FixedAsset(
        branch_id=main_branch.id, code='FA-0001', name='Laptop',
        acquisition_source_type='ap_bill', acquisition_source_id=1,
        acquisition_source_line_id=1, acquisition_date=date(2026, 1, 15),
        acquisition_cost=Decimal('50000.00'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id,
        depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=36,
    )
    db_session.add(asset)
    db_session.commit()
    d = asset.to_dict()
    assert d['code'] == 'FA-0001'
    assert d['status'] == 'active'
    assert d['acquisition_cost'] == 50000.00


def test_tagging_line_twice_rejected(db_session, main_branch):
    cost, accum, exp = _accounts(db_session)
    kwargs = dict(branch_id=main_branch.id, acquisition_date=date(2026, 1, 15),
                  acquisition_cost=Decimal('1000'), cost_account_id=cost.id,
                  accumulated_depreciation_account_id=accum.id,
                  depreciation_expense_account_id=exp.id,
                  depreciation_method='straight_line', useful_life_months=12,
                  acquisition_source_type='ap_bill', acquisition_source_id=5,
                  acquisition_source_line_id=9)
    db_session.add(FixedAsset(code='FA-0001', name='First', **kwargs))
    db_session.commit()
    db_session.add(FixedAsset(code='FA-0002', name='Second', **kwargs))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_multiple_opening_assets_allowed(db_session, main_branch):
    """acquisition_source_type='opening' rows are excluded from the tagging
    uniqueness index (they have no source line to collide on)."""
    cost, accum, exp = _accounts(db_session)
    kwargs = dict(branch_id=main_branch.id, acquisition_date=date(2020, 1, 1),
                  acquisition_cost=Decimal('1000'), cost_account_id=cost.id,
                  accumulated_depreciation_account_id=accum.id,
                  depreciation_expense_account_id=exp.id,
                  depreciation_method='straight_line', useful_life_months=12,
                  acquisition_source_type='opening', acquisition_source_id=None,
                  acquisition_source_line_id=None)
    db_session.add(FixedAsset(code='FA-0003', name='Opening A', **kwargs))
    db_session.commit()
    db_session.add(FixedAsset(code='FA-0004', name='Opening B', **kwargs))
    db_session.commit()  # must NOT raise
    assert FixedAsset.query.filter_by(acquisition_source_type='opening').count() == 2
