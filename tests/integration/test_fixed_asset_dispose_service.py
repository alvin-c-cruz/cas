from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.accounts.models import Account
from app.fixed_assets.models import FixedAsset
from app.fixed_asset_disposal.models import FixedAssetDisposal
from app.fixed_asset_disposal.service import dispose_fixed_asset
from app.journal_entries.models import JournalEntry
from app.settings import AppSettings
from app.audit.models import AuditLog


def _asset(db_session, main_branch, code='FA-D01', cost=Decimal('800000.00'),
          useful_life_months=60, opening_accum=Decimal('0'), cost_code='17901',
          accum_code='17902', exp_code='60902'):
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
        acquisition_date=date(2022, 1, 1), acquisition_cost=cost, cost_account_id=cost_acct.id,
        accumulated_depreciation_account_id=accum_acct.id,
        depreciation_expense_account_id=exp_acct.id, depreciation_method='straight_line',
        useful_life_months=useful_life_months, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=opening_accum, created_by_id=1,
    )
    db_session.add(asset)
    db_session.commit()
    return asset, cost_acct, accum_acct, exp_acct


def _assign_gain_loss_account(db_session, code='80101'):
    account = Account(code=code, name='Gain/Loss on Disposal', account_type='Other Income',
                      normal_balance='Credit')
    db_session.add(account)
    db_session.commit()
    AppSettings.set_setting('gain_loss_on_disposal_account_code', code)
    db_session.commit()
    return account


def _cash_account(db_session, code='10101'):
    account = Account(code=code, name='Cash on Hand', account_type='Asset',
                      normal_balance='Debit')
    db_session.add(account)
    db_session.commit()
    return account


def test_sale_with_gain_posts_balanced_je(db_session, main_branch, admin_user):
    asset, cost_acct, accum_acct, exp_acct = _asset(
        db_session, main_branch, cost=Decimal('800000.00'), useful_life_months=60,
        opening_accum=Decimal('320000.00'))  # NBV = 480000
    gain_loss_acct = _assign_gain_loss_account(db_session)
    cash_acct = _cash_account(db_session)

    disposal = dispose_fixed_asset(asset.id, date(2026, 6, 30), 'sale', Decimal('600000.00'),
                                   cash_acct.id, admin_user.id)

    assert disposal.status == 'posted'
    assert disposal.net_book_value_at_disposal == Decimal('480000.00')
    assert disposal.gain_loss_amount == Decimal('120000.00')  # 600000 - 480000, a GAIN

    db_session.refresh(asset)
    assert asset.status == 'disposed'

    je = db.session.get(JournalEntry, disposal.journal_entry_id)
    assert je.is_balanced
    lines = je.lines.all()
    accum_line = next(l for l in lines if l.account_id == accum_acct.id)
    assert accum_line.debit_amount == Decimal('320000.00')  # prior_accumulated, written off
    cost_line = next(l for l in lines if l.account_id == cost_acct.id)
    assert cost_line.credit_amount == Decimal('800000.00')
    cash_line = next(l for l in lines if l.account_id == cash_acct.id)
    assert cash_line.debit_amount == Decimal('600000.00')
    gain_line = next(l for l in lines if l.account_id == gain_loss_acct.id)
    assert gain_line.credit_amount == Decimal('120000.00')  # gain is a credit

    log = AuditLog.query.filter_by(module='fixed_asset_disposal', action='create',
                                    record_id=disposal.id).first()
    assert log is not None


def test_sale_with_loss_posts_loss_as_debit(db_session, main_branch, admin_user):
    asset, *_ = _asset(db_session, main_branch, cost=Decimal('800000.00'), useful_life_months=60,
                       opening_accum=Decimal('320000.00'))  # NBV = 480000
    gain_loss_acct = _assign_gain_loss_account(db_session)
    cash_acct = _cash_account(db_session)

    disposal = dispose_fixed_asset(asset.id, date(2026, 6, 30), 'sale', Decimal('300000.00'),
                                   cash_acct.id, admin_user.id)
    assert disposal.gain_loss_amount == Decimal('-180000.00')  # 300000 - 480000, a LOSS

    je = db.session.get(JournalEntry, disposal.journal_entry_id)
    assert je.is_balanced
    loss_line = next(l for l in je.lines.all() if l.account_id == gain_loss_acct.id)
    assert loss_line.debit_amount == Decimal('180000.00')  # loss is a debit


def test_scrap_posts_no_proceeds_leg_and_full_loss(db_session, main_branch, admin_user):
    asset, cost_acct, accum_acct, _ = _asset(
        db_session, main_branch, cost=Decimal('800000.00'), useful_life_months=60,
        opening_accum=Decimal('320000.00'))
    gain_loss_acct = _assign_gain_loss_account(db_session)

    disposal = dispose_fixed_asset(asset.id, date(2026, 6, 30), 'scrap', Decimal('0'), None,
                                   admin_user.id)
    assert disposal.proceeds_amount == Decimal('0')
    assert disposal.gain_loss_amount == Decimal('-480000.00')  # full NBV, a loss

    je = db.session.get(JournalEntry, disposal.journal_entry_id)
    assert je.is_balanced
    account_ids = {l.account_id for l in je.lines.all()}
    assert len(account_ids) == 3  # accum, cost, gain/loss -- NO proceeds account leg at all


def test_trade_in_uses_same_shape_as_sale(db_session, main_branch, admin_user):
    asset, *_ = _asset(db_session, main_branch, cost=Decimal('800000.00'), useful_life_months=60,
                       opening_accum=Decimal('320000.00'))
    _assign_gain_loss_account(db_session)
    clearing_acct = Account(code='19901', name='Trade-In Clearing', account_type='Asset',
                            normal_balance='Debit')
    db_session.add(clearing_acct)
    db_session.commit()

    disposal = dispose_fixed_asset(asset.id, date(2026, 6, 30), 'trade_in', Decimal('500000.00'),
                                   clearing_acct.id, admin_user.id)
    assert disposal.disposal_type == 'trade_in'
    je = db.session.get(JournalEntry, disposal.journal_entry_id)
    clearing_line = next(l for l in je.lines.all() if l.account_id == clearing_acct.id)
    assert clearing_line.debit_amount == Decimal('500000.00')


def test_nonzero_proceeds_without_account_rejected(db_session, main_branch, admin_user):
    asset, *_ = _asset(db_session, main_branch)
    _assign_gain_loss_account(db_session)
    with pytest.raises(ValueError, match='proceeds account'):
        dispose_fixed_asset(asset.id, date(2026, 6, 30), 'sale', Decimal('100000.00'), None,
                            admin_user.id)


def test_disposing_an_already_disposed_asset_rejected(db_session, main_branch, admin_user):
    asset, *_ = _asset(db_session, main_branch)
    _assign_gain_loss_account(db_session)
    cash_acct = _cash_account(db_session)
    dispose_fixed_asset(asset.id, date(2026, 6, 30), 'scrap', Decimal('0'), None, admin_user.id)
    with pytest.raises(ValueError, match='active'):
        dispose_fixed_asset(asset.id, date(2026, 6, 30), 'scrap', Decimal('0'), None,
                            admin_user.id)


def test_daily_convention_catch_up_reduces_accum_line_to_prior_only(db_session, main_branch,
                                                                     admin_user):
    """The load-bearing assertion for the JE-construction note: with a nonzero
    final_depreciation_amount catch-up, the Accumulated Depreciation JE line must be
    exactly prior_accumulated (NOT accumulated_depreciation_written_off), and a separate
    Depreciation Expense line carries the catch-up -- the whole JE still balances."""
    AppSettings.set_setting('fixed_asset_depreciation_convention', 'daily')
    db_session.commit()
    asset, cost_acct, accum_acct, exp_acct = _asset(
        db_session, main_branch, cost=Decimal('120000.00'), useful_life_months=12,
        opening_accum=Decimal('0'))
    # straight-line: 120000/12 = 10000/month. Disposed June 15 (2026, 30-day month) ->
    # 15/30 of a month's depreciation = 5000.00 catch-up.
    gain_loss_acct = _assign_gain_loss_account(db_session)
    cash_acct = _cash_account(db_session)

    disposal = dispose_fixed_asset(asset.id, date(2026, 6, 15), 'sale', Decimal('50000.00'),
                                   cash_acct.id, admin_user.id)

    assert disposal.final_depreciation_amount == Decimal('5000.00')
    assert disposal.accumulated_depreciation_written_off == Decimal('5000.00')  # 0 prior + 5000

    je = db.session.get(JournalEntry, disposal.journal_entry_id)
    assert je.is_balanced
    # prior_accumulated was 0, so NO line should exist for the accum-dep account at all
    # (the zero-amount-skip convention) -- assert it's genuinely absent, not present at 0
    accum_lines = [l for l in je.lines.all() if l.account_id == accum_acct.id]
    assert accum_lines == []
    exp_line = next(l for l in je.lines.all() if l.account_id == exp_acct.id)
    assert exp_line.debit_amount == Decimal('5000.00')
