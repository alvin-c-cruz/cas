"""Integration tests -- build_snapshot against real ORM objects."""
import json
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.revisions import build_snapshot, summarize_change, write_revision

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def snapshot_label(so):
    """`"<code> - <name>"` for the order's first line -- matches _line_label."""
    item = so.line_items[0]
    return f'{item.product.code} - {item.product.name}'


@pytest.fixture
def confirmed_so(db_session, main_branch, accountant_user):
    """A confirmed one-line SO built through the ORM: quantity Decimal('3000'),
    unit price Decimal('4.20') -- the exact values that exposed the '3000' vs
    '3000.0000' serialisation defect.

    Deliberately FLUSHES, not commits: the row must exist (so relationships and
    db.session.get() work) but the attributes must still hold the exact
    in-memory Decimals a caller (e.g. the confirm route) would see -- matching
    a form-parsed value, not yet round-tripped through the DB's fixed column
    scale. The test's own commit() is what performs that round trip; expire_on_commit
    (default True) is what forces the re-read afterward.
    """
    from app.customers.models import Customer
    from app.products.models import Product
    from app.sales_orders.models import SalesOrderItem

    customer = Customer(code='C001', name='Test Customer', is_active=True)
    product = Product(code='P031', name='HTA PLASTIC TRAY', is_active=True,
                      track_inventory=False)
    db_session.add_all([customer, product])
    db_session.flush()

    so = SalesOrder(
        branch_id=main_branch.id,
        so_number='2026080001',
        order_date=date(2026, 8, 1),
        expected_delivery_date=date(2026, 8, 10),
        customer_id=customer.id,
        customer_name=customer.name,
        notes='',
        status='confirmed',
        confirmed_by_id=accountant_user.id,
        payment_terms='Net 60',
        subtotal=Decimal('0.00'),
        vat_amount=Decimal('0.00'),
        total_amount=Decimal('0.00'),
        created_by_id=accountant_user.id,
    )
    db_session.add(so)
    db_session.flush()

    item = SalesOrderItem(
        sales_order_id=so.id,
        line_number=1,
        product_id=product.id,
        quantity=Decimal('3000'),
        unit_price=Decimal('4.20'),
        vat_category='V12',
        vat_rate=Decimal('12.00'),
    )
    item.calculate_amounts()
    db_session.add(item)
    db_session.flush()
    # Keep the flushed instance alive here, inside the fixture, by forcing a
    # reference to it via so.line_items[0]. The real mechanism is NOT "first
    # lazy load coerces the value" -- SQLAlchemy's identity map is a
    # WeakInstanceDict, so once the clean flushed instance is garbage
    # collected, the NEXT access reloads it from the row at full column scale
    # (Decimal('3000.0000')). Deferring this reference into the test body left
    # nothing holding the instance alive between the fixture returning and the
    # test's first read, so that first read could already come back at column
    # scale -- which defeated the "form-parsed value" premise this fixture
    # exists to set up.
    so.line_items[0]
    return so


def test_unchanged_order_reports_no_change_across_a_commit_cycle(
        db_session, confirmed_so):
    """THE regression test for the serialisation defect. Snapshot, commit and
    expire so every value is re-read from its column, snapshot again, diff.
    With a raw str(Decimal) this fails on EVERY line -- '3000' from the form
    versus '3000.0000' from Numeric(15,4)."""
    before = build_snapshot(confirmed_so)
    # Pin the premise. Without these the test can pass VACUOUSLY: if `before`
    # were already at column scale, both sides would read '3000.0000' and the
    # bare-str(Decimal) mutation would survive. The fixture keeps the
    # form-shaped instance alive on purpose (SQLAlchemy's identity map is a
    # WeakInstanceDict -- once the clean flushed instance is collected, the
    # collection reloads it from the row at full column scale).
    assert before['lines'][0]['quantity'] == '3000'

    db_session.commit()
    db_session.expire_all()
    reloaded = db_session.get(SalesOrder, confirmed_so.id)
    after = build_snapshot(reloaded)
    assert reloaded.line_items[0].quantity == Decimal('3000.0000')

    assert summarize_change(before, after)['changes'] == []


def test_snapshot_carries_the_real_line_id(db_session, confirmed_so):
    snap = build_snapshot(confirmed_so)
    assert snap['lines'][0]['line_id'] == confirmed_so.line_items[0].id


def test_snapshot_is_json_serialisable(db_session, confirmed_so):
    """write_revision stores json.dumps(snapshot); an unconverted Decimal or
    date would raise only at write time, in production."""
    json.dumps(build_snapshot(confirmed_so))


def test_quantity_edit_through_the_orm_is_reported_once(db_session, confirmed_so):
    before = build_snapshot(confirmed_so)
    confirmed_so.line_items[0].quantity = Decimal('7000')
    db_session.flush()
    after = build_snapshot(confirmed_so)
    assert summarize_change(before, after)['changes'] == [{
        'kind': 'qty', 'line': snapshot_label(confirmed_so),
        'old': '3000', 'new': '7000'}]


def test_renumbering_lines_on_reorder_is_not_a_change(db_session, main_branch,
                                                       accountant_user):
    """SalesOrderItem.id is a global autoincrement independent of line_number,
    which is per-order and gets REASSIGNED when the amend UI lets a user
    reorder lines. Identity must ride on id, not line_number -- two lines that
    swap line_number (their displayed position) but keep their own id/content
    must diff as unchanged. Keying the diff on line_number instead would
    silently re-pair the two DIFFERENT lines with each other and report a
    fabricated edit."""
    from app.customers.models import Customer
    from app.products.models import Product
    from app.sales_orders.models import SalesOrderItem

    customer = Customer(code='C002', name='Renumber Test Customer', is_active=True)
    tray = Product(code='P031', name='HTA PLASTIC TRAY', is_active=True,
                   track_inventory=False)
    tub = Product(code='P022', name='GRAHAMS LONGTUB', is_active=True,
                 track_inventory=False)
    db_session.add_all([customer, tray, tub])
    db_session.flush()

    so = SalesOrder(
        branch_id=main_branch.id, so_number='2026080002',
        order_date=date(2026, 8, 1), customer_id=customer.id,
        customer_name=customer.name, notes='', status='confirmed',
        confirmed_by_id=accountant_user.id, payment_terms='Net 60',
        subtotal=Decimal('0.00'), vat_amount=Decimal('0.00'),
        total_amount=Decimal('0.00'), created_by_id=accountant_user.id,
    )
    db_session.add(so)
    db_session.flush()

    item_a = SalesOrderItem(sales_order_id=so.id, line_number=1,
                            product_id=tray.id, quantity=Decimal('3000'),
                            unit_price=Decimal('4.20'))
    item_b = SalesOrderItem(sales_order_id=so.id, line_number=2,
                            product_id=tub.id, quantity=Decimal('500'),
                            unit_price=Decimal('10.00'))
    item_a.calculate_amounts()
    item_b.calculate_amounts()
    db_session.add_all([item_a, item_b])
    db_session.flush()
    so.line_items[0]  # force the first lazy load -- see confirmed_so fixture.

    before = build_snapshot(so)

    # Simulate a UI reorder: the two lines swap DISPLAY position/line_number,
    # but each row keeps its own id and its own content.
    item_a.line_number, item_b.line_number = 2, 1
    db_session.flush()

    after = build_snapshot(so)

    assert summarize_change(before, after)['changes'] == []


def test_write_revision_flushes_before_snapshotting_an_appended_line(
        db_session, confirmed_so, accountant_user):
    """The amend route (Task 6) may append a new SalesOrderItem without an
    explicit flush of its own; write_revision must flush before either
    snapshot is built, because the diff's identity is the row id. Without that
    flush, the added line's id is still None and hits the fail-closed guard in
    _by_line_id -- it must RAISE, never silently vanish from a revision that
    carries a reason and an authorizing PO."""
    write_revision(confirmed_so, user_id=accountant_user.id)  # revision 0
    db_session.flush()

    new_item = SalesOrderItem(
        line_number=2, product_id=confirmed_so.line_items[0].product_id,
        quantity=Decimal('10'), unit_price=Decimal('1.00'))
    new_item.calculate_amounts()
    # Append to the relationship collection (as the amend route does), not a
    # bare FK assignment -- so.line_items was already loaded by the fixture,
    # and only appending updates that cached in-memory collection immediately.
    confirmed_so.line_items.append(new_item)
    # Deliberately NOT flushed here -- new_item.id is still None at this point.

    rev = write_revision(confirmed_so, user_id=accountant_user.id,
                         reason='add tranche')
    summary = json.loads(rev.change_summary)
    added = [c for c in summary['changes'] if c['kind'] == 'added']
    assert len(added) == 1


def test_write_revisions_own_flush_does_not_depend_on_caller_autoflush(
        db_session, confirmed_so, accountant_user):
    """write_revision's internal flush must hold even when the SESSION's
    autoflush is suppressed around the call -- as app/utils/concurrency.py
    does elsewhere in this codebase (db.session.no_autoflush) to dodge a
    premature query-triggered flush. Inside that context, latest_revision()'s
    own query can no longer implicitly flush a pending appended line for us;
    only write_revision's explicit db.session.flush() can. Without it the
    appended line's id stays None and the fail-closed _by_line_id guard
    raises instead of completing."""
    write_revision(confirmed_so, user_id=accountant_user.id)
    db_session.flush()

    new_item = SalesOrderItem(
        line_number=2, product_id=confirmed_so.line_items[0].product_id,
        quantity=Decimal('10'), unit_price=Decimal('1.00'))
    new_item.calculate_amounts()
    confirmed_so.line_items.append(new_item)

    with db.session.no_autoflush:
        rev = write_revision(confirmed_so, user_id=accountant_user.id,
                             reason='add tranche')

    summary = json.loads(rev.change_summary)
    added = [c for c in summary['changes'] if c['kind'] == 'added']
    assert len(added) == 1
