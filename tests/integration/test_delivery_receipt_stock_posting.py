# tests/integration/test_delivery_receipt_stock_posting.py
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.delivery_receipts.stock_posting import post_dr_delivery, reverse_dr_delivery
from app.stock_adjustments.models import StockMovement, StockBalance
from app.stock_adjustments.service import post_movement
from app.posting.control_accounts import ControlAccountError
from app.settings import AppSettings
from app.customers.models import Customer
from app.sales_orders.models import SalesOrder, SalesOrderItem

pytestmark = [pytest.mark.integration]


def _assign(code_setting, code, account_factory):
    account_factory(code)
    AppSettings.set_setting(code_setting, code, updated_by='test')


def _confirmed_so(db_session, branch, product, qty=10):
    c = Customer(code='C-2A3', name='Acme 2a3', is_active=True)
    db.session.add(c); db.session.commit()
    so = SalesOrder(so_number='SO-2A3-0001', order_date=date(2026, 7, 21), customer_id=c.id,
                    customer_name=c.name, branch_id=branch.id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, product_id=product.id, quantity=Decimal(str(qty)),
                                        unit_price=Decimal('50.00'), amount=Decimal(str(qty * 50))))
    db.session.add(so); db.session.commit()
    return so


def _delivered_dr(db_session, branch, so, delivered_qty, number='DR-2A3-0001'):
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    dr = DeliveryReceipt(branch_id=branch.id, dr_number=number, delivery_date=date(2026, 7, 21),
                         sales_order_id=so.id, customer_id=so.customer_id, customer_name=so.customer_name,
                         status='approved')
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=so.line_items[0].id,
                                             product_id=so.line_items[0].product_id,
                                             delivered_quantity=Decimal(str(delivered_qty))))
    db.session.add(dr); db.session.commit()
    return dr


def test_tracked_line_posts_issue_at_current_average(
        db_session, branch_main, admin_user, product_tracked, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('cogs_account_code', '61060', make_account)
    # Seed a real prior balance: 20 @ 8.00 -> avg 8.00
    post_movement(product_tracked, branch_main.id, 'receipt', Decimal('20'), Decimal('8.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=6)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=6)

    post_dr_delivery(dr, admin_user)
    db.session.commit()

    assert dr.journal_entry_id is not None
    assert dr.journal_entry.is_balanced
    mv = StockMovement.query.filter_by(source_document_type='delivery_receipt', source_document_id=dr.id).one()
    assert mv.quantity == Decimal('-6.0000')
    assert mv.unit_cost == Decimal('8.00')   # current average, UNCHANGED by the issue
    dr_line = next(l for l in dr.journal_entry.lines if l.account.code == '61060')
    cr_line = next(l for l in dr.journal_entry.lines if l.account.code == '1401')
    assert dr_line.debit_amount == Decimal('48.00') and cr_line.credit_amount == Decimal('48.00')
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('14.0000')
    assert bal.average_unit_cost == Decimal('8.00')   # unchanged by the issue


def test_untracked_line_posts_nothing(db_session, branch_main, admin_user, make_account):
    from app.products.models import Product
    untracked = Product(code='UNTRK-2A3', name='Untracked 2a3', track_inventory=False, is_active=True)
    db.session.add(untracked); db.session.commit()
    so = _confirmed_so(db_session, branch_main, untracked, qty=5)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=5)

    post_dr_delivery(dr, admin_user)  # no accounts assigned at all -- must not raise
    db.session.commit()

    assert dr.journal_entry_id is None
    assert StockMovement.query.count() == 0


def test_fails_closed_before_any_write_when_cogs_unassigned(
        db_session, branch_main, admin_user, product_tracked, make_account):
    _assign('inventory_account_code', '1401', make_account)  # cogs left unassigned
    post_movement(product_tracked, branch_main.id, 'receipt', Decimal('10'), Decimal('5.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=3)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=3)

    with pytest.raises(ControlAccountError):
        post_dr_delivery(dr, admin_user)
    assert dr.journal_entry_id is None
    assert StockMovement.query.filter_by(source_document_type='delivery_receipt').count() == 0


def test_negative_on_hand_delivery_posts_with_warning(
        db_session, branch_main, admin_user, product_tracked, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('cogs_account_code', '61060', make_account)
    # No prior receipt -- shipping from zero on-hand.
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=3)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=3)

    post_dr_delivery(dr, admin_user)  # must not raise
    db.session.commit()
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('-3.0000')


def test_reverse_dr_delivery_reverses_movement_and_posts_reversing_je(
        db_session, branch_main, admin_user, product_tracked, make_account):
    from app.journal_entries.models import JournalEntry
    _assign('inventory_account_code', '1401', make_account)
    _assign('cogs_account_code', '61060', make_account)
    post_movement(product_tracked, branch_main.id, 'receipt', Decimal('20'), Decimal('8.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=6)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=6)
    post_dr_delivery(dr, admin_user); db.session.commit()
    original_je_id = dr.journal_entry_id

    reverse_dr_delivery(dr, admin_user)
    db.session.commit()

    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('20.0000')   # back to the seeded 20
    jes = JournalEntry.query.filter_by(reference=dr.dr_number).order_by(JournalEntry.id).all()
    assert len(jes) == 2
    assert jes[1].id != original_je_id
    reversal_mv = (StockMovement.query
                  .filter_by(source_document_type='delivery_receipt', source_document_id=dr.id)
                  .filter(StockMovement.quantity > 0).one())
    assert reversal_mv.journal_entry_id == jes[1].id


def test_reverse_dr_delivery_noop_when_never_posted(db_session, branch_main, admin_user, make_account):
    from app.products.models import Product
    untracked = Product(code='UNTRK-2A3B', name='Untracked 2a3b', track_inventory=False, is_active=True)
    db.session.add(untracked); db.session.commit()
    so = _confirmed_so(db_session, branch_main, untracked, qty=2)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=2)
    post_dr_delivery(dr, admin_user); db.session.commit()

    reverse_dr_delivery(dr, admin_user)  # no JE was ever posted -- must be a clean no-op
    db.session.commit()
    from app.journal_entries.models import JournalEntry
    assert JournalEntry.query.filter_by(reference=dr.dr_number).count() == 0


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable_dr():
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db.session.commit(); clear_module_config_cache()


def test_deliver_route_posts_cogs_je(
        client, db_session, admin_user, branch_main, product_tracked, make_account):
    _enable_dr()
    _assign('inventory_account_code', '1401', make_account)
    _assign('cogs_account_code', '61060', make_account)
    post_movement(product_tracked, branch_main.id, 'receipt', Decimal('20'), Decimal('8.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=6)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=6)   # status='approved'
    _login(client, admin_user, branch_main)

    resp = client.post(f'/delivery-receipts/{dr.id}/deliver', follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(dr)
    assert dr.status == 'delivered'
    assert dr.journal_entry_id is not None


def test_deliver_route_fails_closed_leaves_approved(
        client, db_session, admin_user, branch_main, product_tracked, make_account):
    _enable_dr()
    # No control accounts assigned at all.
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=3)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=3)
    _login(client, admin_user, branch_main)

    resp = client.post(f'/delivery-receipts/{dr.id}/deliver', follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(dr)
    assert dr.status == 'approved'   # still approved -- delivery did NOT silently half-succeed


def test_cancel_route_reverses_cogs_je_when_delivered(
        client, db_session, admin_user, branch_main, product_tracked, make_account):
    _enable_dr()
    _assign('inventory_account_code', '1401', make_account)
    _assign('cogs_account_code', '61060', make_account)
    post_movement(product_tracked, branch_main.id, 'receipt', Decimal('20'), Decimal('8.00'),
                  'seed', None, 'seed stock', admin_user)
    db.session.commit()
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=6)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=6)
    _login(client, admin_user, branch_main)
    client.post(f'/delivery-receipts/{dr.id}/deliver', follow_redirects=True)
    db.session.refresh(dr)
    assert dr.status == 'delivered' and dr.journal_entry_id is not None

    resp = client.post(f'/delivery-receipts/{dr.id}/cancel',
                       data={'cancel_reason': 'Customer refused the shipment'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(dr)
    assert dr.status == 'cancelled'
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('20.0000')   # back to the seeded 20


def test_cancel_route_noop_when_cancelled_before_delivery(
        client, db_session, admin_user, branch_main, product_tracked, make_account):
    _enable_dr()
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=6)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=6)   # status='approved', never delivered
    _login(client, admin_user, branch_main)

    resp = client.post(f'/delivery-receipts/{dr.id}/cancel',
                       data={'cancel_reason': 'Order changed before shipping'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(dr)
    assert dr.status == 'cancelled'
    assert dr.journal_entry_id is None   # nothing was ever posted -- clean no-op, no error
