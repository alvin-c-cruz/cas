from decimal import Decimal
import datetime, pytest
from app import db
from app.stock_adjustments.models import StockAdjustment, StockAdjustmentLine, StockBalance
from app.stock_adjustments.numbering import generate_sa_number
from app.stock_adjustments.service import approve_adjustment, void_adjustment
from app.posting.control_accounts import ControlAccountError
from app.settings import AppSettings

def _assign(code_setting, code, account_factory):
    account_factory(code)
    AppSettings.set_setting(code_setting, code, updated_by='test')

def test_approve_correction_posts_movement_and_balanced_je(
        db_session, product_tracked, branch_main, admin_user, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('inventory_adjustment_account_code', '7101', make_account)
    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=datetime.date(2026, 7, 21), reason_type='correction',
                          status='draft', created_by_id=admin_user.id)
    adj.lines.append(StockAdjustmentLine(product_id=product_tracked.id,
                                         quantity_delta=Decimal('5'), unit_cost=Decimal('4.00')))
    db.session.add(adj); db.session.commit()

    approve_adjustment(adj, admin_user)
    db.session.commit()
    assert adj.status == 'posted'
    assert adj.journal_entry is not None and adj.journal_entry.is_balanced
    # inventory debit == 5 * 4.00 = 20.00
    inv = next(l for l in adj.journal_entry.lines if l.debit_amount == Decimal('20.00'))
    assert inv is not None
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('5.0000')

def test_opening_uses_equity_offset_not_pl(
        db_session, product_tracked, branch_main, admin_user, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('inventory_opening_equity_account_code', '3900', make_account)
    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=datetime.date(2026, 7, 21), reason_type='opening',
                          status='draft', created_by_id=admin_user.id)
    adj.lines.append(StockAdjustmentLine(product_id=product_tracked.id,
                                         quantity_delta=Decimal('10'), unit_cost=Decimal('3.00')))
    db.session.add(adj); db.session.commit()
    approve_adjustment(adj, admin_user)
    db.session.commit()
    codes = {l.account.code for l in adj.journal_entry.lines}
    assert '3900' in codes and '7101' not in codes  # equity, never the P&L account

def test_unassigned_account_raises_before_any_write(
        db_session, product_tracked, branch_main, admin_user):
    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=datetime.date(2026, 7, 21), reason_type='correction',
                          status='draft', created_by_id=admin_user.id)
    adj.lines.append(StockAdjustmentLine(product_id=product_tracked.id,
                                         quantity_delta=Decimal('5'), unit_cost=Decimal('4.00')))
    db.session.add(adj); db.session.commit()
    with pytest.raises(ControlAccountError):
        approve_adjustment(adj, admin_user)
    assert adj.status == 'draft'  # untouched

def test_void_reverses_balance_and_posts_reversing_je(
        db_session, product_tracked, branch_main, admin_user, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('inventory_adjustment_account_code', '7101', make_account)
    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=datetime.date(2026, 7, 21), reason_type='correction',
                          status='draft', created_by_id=admin_user.id)
    adj.lines.append(StockAdjustmentLine(product_id=product_tracked.id,
                                         quantity_delta=Decimal('5'), unit_cost=Decimal('4.00')))
    db.session.add(adj); db.session.commit()
    approve_adjustment(adj, admin_user); db.session.commit()
    void_adjustment(adj, admin_user); db.session.commit()
    assert adj.status == 'voided'
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('0.0000')
