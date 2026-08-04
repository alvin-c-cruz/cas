"""Integration tests -- build_snapshot / write_revision against real ORM objects."""
import json
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.sales_orders.models import SalesOrder
from app.sales_orders.revision_models import SalesOrderRevision
from app.sales_orders.revisions import build_snapshot, write_revision, latest_revision

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture
def product_factory(db_session):
    """Create a distinct active Product on each call."""
    from app.products.models import Product
    counter = {'n': 0}

    def _make():
        counter['n'] += 1
        product = Product(code=f'P{counter["n"]:03d}', name=f'Test Product {counter["n"]}',
                          is_active=True, track_inventory=False)
        db_session.add(product)
        db_session.flush()
        return product

    return _make


@pytest.fixture
def confirmed_so(db_session, main_branch, accountant_user, product_factory):
    """A confirmed one-line SO built through the ORM: quantity Decimal('3000'),
    unit price Decimal('4.20') -- the exact values that exposed the '3000' vs
    '3000.0000' serialisation defect.

    Deliberately FLUSHES, not commits: the row must exist (so relationships and
    db.session.get() work) but the attributes must still hold the exact
    in-memory Decimals a caller (e.g. the confirm route) would see -- matching
    a form-parsed value, not yet round-tripped through the DB's fixed column
    scale. The test's own commit() is what performs that round trip;
    expire_on_commit (default True) is what forces the re-read afterward.

    The line instance must be kept referenced here, inside the fixture, by
    touching so.line_items before returning. SQLAlchemy's identity map is a
    WeakInstanceDict: once the clean flushed instance is garbage collected, the
    NEXT access reloads it from the row at full column scale
    (Decimal('3000.0000')) -- which would defeat the "form-parsed value"
    premise this fixture exists to set up, and make
    test_snapshot_is_stable_across_a_commit_cycle pass vacuously (both sides
    already at column scale before the test's own commit/expire even runs).
    """
    from app.customers.models import Customer
    from app.sales_orders.models import SalesOrderItem

    customer = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(customer)
    db_session.flush()

    product = product_factory()

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
    # See docstring above -- keep the flushed instance alive by referencing it.
    so.line_items[0]
    return so


def test_snapshot_is_stable_across_a_commit_cycle(db_session, confirmed_so):
    """THE regression test. Snapshot, commit and expire so every value is re-read
    from its column, snapshot again -- the two must be EQUAL. With a bare
    str(Decimal) they differ on every numeric field ('3000' vs '3000.0000'),
    which is what made an earlier diff implementation inert against real data."""
    before = build_snapshot(confirmed_so)
    assert before['lines'][0]['quantity'] == '3000'

    db_session.commit()
    db_session.expire_all()
    reloaded = db_session.get(SalesOrder, confirmed_so.id)
    assert reloaded.line_items[0].quantity == Decimal('3000.0000')

    assert build_snapshot(reloaded) == before


def test_snapshot_carries_the_real_line_id(db_session, confirmed_so):
    snap = build_snapshot(confirmed_so)
    assert snap['lines'][0]['line_id'] == confirmed_so.line_items[0].id


def test_snapshot_is_json_serialisable(db_session, confirmed_so):
    """write_revision stores json.dumps(snapshot); an unconverted Decimal or date
    would raise only at write time, in production."""
    json.dumps(build_snapshot(confirmed_so))


def test_snapshot_resolves_fk_values_to_readable_names(db_session, confirmed_so):
    """The snapshot is RENDERED to a human, so a bare FK integer is useless."""
    line = build_snapshot(confirmed_so)['lines'][0]
    assert line['product_code'] == confirmed_so.line_items[0].product.code
    assert line['product_name'] == confirmed_so.line_items[0].product.name
    assert 'delivery_site_name' in line and 'wt_code' in line and 'uom_display' in line


def test_write_revision_numbers_from_zero_and_does_not_commit(db_session, confirmed_so):
    rev = write_revision(confirmed_so, user_id=None)
    assert rev.revision_number == 0
    assert rev.reason is None
    db_session.rollback()
    assert SalesOrderRevision.query.filter_by(sales_order_id=confirmed_so.id).count() == 0


def test_write_revision_increments_and_records_reason_and_po(db_session, confirmed_so):
    write_revision(confirmed_so, user_id=None)
    db_session.commit()
    rev = write_revision(confirmed_so, user_id=None, reason='PO received after job order',
                         authorizing_po='PO-MMS-88421')
    db_session.commit()
    assert rev.revision_number == 1
    assert rev.reason == 'PO received after job order'
    assert rev.authorizing_po_number == 'PO-MMS-88421'
    assert latest_revision(confirmed_so.id).revision_number == 1


def test_write_revisions_own_flush_does_not_depend_on_caller_autoflush(
        db_session, confirmed_so, product_factory):
    """A line appended but unflushed has id None, and the snapshot's identity
    depends on that id. Default autoflush would mask a missing explicit flush,
    so this pins it inside no_autoflush."""
    from app.sales_orders.models import SalesOrderItem
    item = SalesOrderItem(sales_order_id=confirmed_so.id, line_number=2,
                          product_id=product_factory().id, quantity=Decimal('500'),
                          unit_price=Decimal('1.00'), amount=Decimal('500.00'))
    confirmed_so.line_items.append(item)
    with db_session.no_autoflush:
        rev = write_revision(confirmed_so, user_id=None)
    ids = [l['line_id'] for l in json.loads(rev.snapshot_json)['lines']]
    assert None not in ids and len(ids) == 2


def test_snapshot_captures_confirmation_provenance(db_session, confirmed_so):
    """Rev 0 is 'the order as originally confirmed' -- a snapshot that cannot say
    who confirmed it is not the complete record this now claims to be."""
    header = build_snapshot(confirmed_so)['header']
    for field in ('confirmed_by_id', 'confirmed_at',
                  'cancelled_by_id', 'cancelled_at', 'cancel_reason'):
        assert field in header
    line = build_snapshot(confirmed_so)['lines'][0]
    for field in ('vat_amount', 'closed_by_id', 'closed_at', 'closed_reason'):
        assert field in line
