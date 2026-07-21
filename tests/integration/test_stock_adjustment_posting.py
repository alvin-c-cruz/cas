from decimal import Decimal
import datetime, pytest
from app import db
from app.products.models import Product
from app.stock_adjustments.models import StockAdjustment, StockAdjustmentLine, StockBalance
from app.stock_adjustments.numbering import generate_sa_number
from app.stock_adjustments.service import approve_adjustment, void_adjustment, post_movement
from app.posting.control_accounts import ControlAccountError
from app.settings import AppSettings

def _assign(code_setting, code, account_factory):
    account_factory(code)
    AppSettings.set_setting(code_setting, code, updated_by='test')

def _leg(je, code):
    """The single JE line posted to the account with this code."""
    return next(l for l in je.lines if l.account.code == code)

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


def test_negative_correction_line_valued_at_prior_balance_average_not_entered_cost(
        db_session, product_tracked, branch_main, admin_user, make_account):
    """A NEGATIVE line on a moving_average product is valued at the balance's
    average_unit_cost AS IT STOOD BEFORE this adjustment -- NOT the entered
    unit_cost. Seed a real average (10 @ 6.00), then remove 4 units while
    passing an obviously-wrong entered unit_cost (99.00): the JE must value the
    removal at 4 * 6.00 = 24.00, proving the entered cost is unused."""
    _assign('inventory_account_code', '1401', make_account)
    _assign('inventory_adjustment_account_code', '7101', make_account)
    # Seed an existing balance: receipt of 10 @ 6.00 -> avg 6.00.
    post_movement(product_tracked, branch_main.id, 'receipt', Decimal('10'),
                  Decimal('6.00'), 'seed', None, 'seed stock', admin_user)
    db.session.commit()
    seeded = StockBalance.query.filter_by(
        product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert seeded.average_unit_cost == Decimal('6.00')

    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=datetime.date(2026, 7, 21), reason_type='correction',
                          status='draft', created_by_id=admin_user.id)
    # entered unit_cost 99.00 is a decoy -- a negative line must ignore it.
    adj.lines.append(StockAdjustmentLine(product_id=product_tracked.id,
                                         quantity_delta=Decimal('-4'), unit_cost=Decimal('99.00')))
    db.session.add(adj); db.session.commit()

    approve_adjustment(adj, admin_user)
    db.session.commit()
    assert adj.status == 'posted'
    je = adj.journal_entry
    assert je is not None and je.is_balanced
    expected = Decimal('24.00')             # abs(-4) * prior avg 6.00, NOT 4 * 99.00
    # stock out: Dr inventory_adjustment (7101) / Cr inventory (1401)
    dr = _leg(je, '7101')
    cr = _leg(je, '1401')
    assert dr.debit_amount == expected and dr.credit_amount == Decimal('0.00')
    assert cr.credit_amount == expected and cr.debit_amount == Decimal('0.00')
    # remaining balance: 10 - 4 = 6, average untouched at 6.00
    bal = StockBalance.query.filter_by(
        product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('6.0000')
    assert bal.average_unit_cost == Decimal('6.00')


def test_standard_cost_positive_line_uses_standard_not_entered_cost(
        db_session, branch_main, admin_user, make_account):
    """A POSITIVE line on a STANDARD-costed product values the inventory leg at
    Product.standard_cost, NOT the entered unit_cost. Entered cost 5.00 differs
    from standard_cost 8.00: the JE inventory leg must be 3 * 8.00 = 24.00."""
    _assign('inventory_account_code', '1401', make_account)
    _assign('inventory_adjustment_account_code', '7101', make_account)
    prod = Product(code='STK-STD', name='Standard Item', track_inventory=True,
                   costing_method='standard', standard_cost=Decimal('8.00'), is_active=True)
    db.session.add(prod); db.session.commit()

    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=datetime.date(2026, 7, 21), reason_type='correction',
                          status='draft', created_by_id=admin_user.id)
    adj.lines.append(StockAdjustmentLine(product_id=prod.id,
                                         quantity_delta=Decimal('3'), unit_cost=Decimal('5.00')))
    db.session.add(adj); db.session.commit()

    approve_adjustment(adj, admin_user)
    db.session.commit()
    assert adj.status == 'posted'
    je = adj.journal_entry
    assert je is not None and je.is_balanced
    expected = Decimal('24.00')             # 3 * standard 8.00, NOT 3 * entered 5.00
    # stock in: Dr inventory (1401) / Cr inventory_adjustment (7101)
    dr = _leg(je, '1401')
    cr = _leg(je, '7101')
    assert dr.debit_amount == expected and dr.credit_amount == Decimal('0.00')
    assert cr.credit_amount == expected and cr.debit_amount == Decimal('0.00')
    # 3 * entered 5.00 = 15.00 must appear NOWHERE in the JE
    assert all(l.debit_amount != Decimal('15.00') and l.credit_amount != Decimal('15.00')
               for l in je.lines)


def test_negative_opening_line_debits_equity_credits_inventory(
        db_session, product_tracked, branch_main, admin_user, make_account):
    """A NEGATIVE line on an OPENING adjustment posts Dr inventory_opening_equity
    (3900) / Cr inventory (1401) -- the equity account on the DEBIT side for a
    decrease. Confirms the Dr/Cr direction for opening+negative, complementing
    the positive+opening case already covered. Seed 10 @ 3.00, remove 4 -> 12.00."""
    _assign('inventory_account_code', '1401', make_account)
    _assign('inventory_opening_equity_account_code', '3900', make_account)
    # Seed an existing balance to value the removal against: 10 @ 3.00 -> avg 3.00.
    post_movement(product_tracked, branch_main.id, 'receipt', Decimal('10'),
                  Decimal('3.00'), 'seed', None, 'seed stock', admin_user)
    db.session.commit()

    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=datetime.date(2026, 7, 21), reason_type='opening',
                          status='draft', created_by_id=admin_user.id)
    adj.lines.append(StockAdjustmentLine(product_id=product_tracked.id,
                                         quantity_delta=Decimal('-4'), unit_cost=None))
    db.session.add(adj); db.session.commit()

    approve_adjustment(adj, admin_user)
    db.session.commit()
    assert adj.status == 'posted'
    je = adj.journal_entry
    assert je is not None and je.is_balanced
    expected = Decimal('12.00')             # abs(-4) * prior avg 3.00
    dr = _leg(je, '3900')                    # equity DEBITED on a decrease
    cr = _leg(je, '1401')                    # inventory CREDITED
    assert dr.debit_amount == expected and dr.credit_amount == Decimal('0.00')
    assert cr.credit_amount == expected and cr.debit_amount == Decimal('0.00')
    codes = {l.account.code for l in je.lines}
    assert '7101' not in codes               # never the P&L offset for an opening adjustment
