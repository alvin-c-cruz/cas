from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from app import db
from app.fixed_asset_disposal.models import FixedAssetDisposal
from app.fixed_assets.models import FixedAsset
from app.accounts.models import Account


def _asset(db_session, main_branch, code='FA-X001'):
    cost = Account(code='17801', name='Vehicle - Cost', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17802', name='Vehicle - Accum. Dep.', account_type='Asset',
                    normal_balance='Credit')
    exp = Account(code='60901', name='Depreciation Expense', account_type='Expense',
                  normal_balance='Debit')
    db_session.add_all([cost, accum, exp])
    db_session.commit()
    asset = FixedAsset(
        branch_id=main_branch.id, code=code, name='Delivery Van',
        acquisition_source_type='opening', acquisition_source_id=None,
        acquisition_source_line_id=None, acquisition_date=date(2022, 1, 1),
        acquisition_cost=Decimal('800000.00'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=60, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )
    db_session.add(asset)
    db_session.commit()
    return asset


def test_disposal_to_dict(db_session, main_branch):
    asset = _asset(db_session, main_branch)
    disposal = FixedAssetDisposal(
        fixed_asset_id=asset.id, disposal_date=date(2026, 6, 30), disposal_type='sale',
        proceeds_amount=Decimal('300000.00'), final_depreciation_amount=Decimal('0'),
        cost_written_off=Decimal('800000.00'),
        accumulated_depreciation_written_off=Decimal('320000.00'),
        net_book_value_at_disposal=Decimal('480000.00'),
        gain_loss_amount=Decimal('-180000.00'), status='posted', created_by_id=1,
    )
    db_session.add(disposal)
    db_session.commit()

    d = disposal.to_dict()
    assert d['fixed_asset_id'] == asset.id
    assert d['disposal_type'] == 'sale'
    assert d['gain_loss_amount'] == -180000.00
    assert d['status'] == 'posted'


def test_second_posted_disposal_for_same_asset_rejected(db_session, main_branch):
    asset = _asset(db_session, main_branch)
    kwargs = dict(disposal_date=date(2026, 6, 30), disposal_type='scrap',
                  proceeds_amount=Decimal('0'), final_depreciation_amount=Decimal('0'),
                  cost_written_off=Decimal('800000.00'),
                  accumulated_depreciation_written_off=Decimal('800000.00'),
                  net_book_value_at_disposal=Decimal('0'), gain_loss_amount=Decimal('0'),
                  status='posted', created_by_id=1)
    db_session.add(FixedAssetDisposal(fixed_asset_id=asset.id, **kwargs))
    db_session.commit()
    db_session.add(FixedAssetDisposal(fixed_asset_id=asset.id, **kwargs))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_voided_disposal_frees_the_asset_for_a_new_disposal(db_session, main_branch):
    asset = _asset(db_session, main_branch)
    kwargs = dict(disposal_date=date(2026, 6, 30), disposal_type='scrap',
                  proceeds_amount=Decimal('0'), final_depreciation_amount=Decimal('0'),
                  cost_written_off=Decimal('800000.00'),
                  accumulated_depreciation_written_off=Decimal('800000.00'),
                  net_book_value_at_disposal=Decimal('0'), gain_loss_amount=Decimal('0'),
                  created_by_id=1)
    d1 = FixedAssetDisposal(fixed_asset_id=asset.id, status='posted', **kwargs)
    db_session.add(d1)
    db_session.commit()
    d1.status = 'void'
    db_session.commit()

    db_session.add(FixedAssetDisposal(fixed_asset_id=asset.id, status='posted', **kwargs))
    db_session.commit()  # must NOT raise
    assert FixedAssetDisposal.query.filter_by(fixed_asset_id=asset.id).count() == 2
