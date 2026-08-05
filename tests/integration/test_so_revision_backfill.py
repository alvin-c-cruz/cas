"""The backfill migration must reconstruct a Rev 0 that matches build_snapshot()'s
own key set and render-critical values -- not merely round-trip a hand-built row.

An earlier version of this test built a SalesOrderRevision directly in the test
session and asserted a string round-trip. That observes nothing about the
migration: replacing sorev_0002.upgrade() with `return` still left it passing.
This drives the REAL upgrade()/downgrade() functions against the test session's
own connection via Alembic's Operations/MigrationContext -- the same primitive
`flask db upgrade` uses under the hood -- against confirmed Sales Orders with
real lines built through the ORM. See CLAUDE.md's "Migrations are HAND-WRITTEN
with batch ops" gotcha and memory `migration-verify-on-real-db-copy`: a
conftest create_all() DB is not a migrated DB, but the migration's own upgrade()
function IS the code under test here, so invoking it directly (rather than a
subprocess `flask db upgrade`) is both faithful and fast.
"""
import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.revision_models import SalesOrderRevision
from app.sales_orders.revisions import build_snapshot, write_revision

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

RECONSTRUCTED = 'Rev 0 - reconstructed at upgrade, not an original capture'

_MIGRATION_PATH = (Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
                   / 'sorev_0002_backfill_rev0.py')


def _load_migration():
    """Import the migration module fresh each call (migrations/versions has no
    __init__.py, so this is a plain file-path import rather than a package
    import)."""
    spec = importlib.util.spec_from_file_location('sorev_0002_backfill_rev0', _MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bind_op(db_session):
    """Bind Alembic's `op` to the test session's own live connection, so the
    migration's raw sa.text() statements land in the SAME transaction the ORM
    queries below read back from."""
    connection = db_session.connection()
    ctx = MigrationContext.configure(connection)
    return Operations(ctx)


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch(code='CORP', name='CORP')
    db_session.add(b)
    db_session.commit()
    return b


@pytest.fixture
def customer(db_session):
    from app.customers.models import Customer, CustomerDeliverySite
    c = Customer(code='ACME01', name='Acme Trading', tin='123-456-789-000',
                address='123 Industrial Ave', is_active=True)
    db_session.add(c)
    db_session.commit()
    site = CustomerDeliverySite(customer_id=c.id, name='Main Warehouse', is_active=True)
    db_session.add(site)
    db_session.commit()
    c.site = site
    return c


@pytest.fixture
def product(db_session):
    from app.units_of_measure.models import UnitOfMeasure
    from app.products.models import Product
    uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db_session.add(uom)
    db_session.commit()
    p = Product(code='WIDGET', name='Widget', default_unit_of_measure_id=uom.id,
               default_unit_price=Decimal('100.00'), is_active=True)
    db_session.add(p)
    db_session.commit()
    p.uom = uom
    return p


@pytest.fixture
def salesperson(db_session, branch):
    from app.employees.models import Employee
    e = Employee(employee_no='EMP001', first_name='Juan', middle_name='Dela',
                last_name='Cruz', branch_id=branch.id)
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture
def wht(db_session):
    from app.withholding_tax.models import WithholdingTax
    w = WithholdingTax(code='WC160', name='Goods - individual', rate=Decimal('1.00'))
    db_session.add(w)
    db_session.commit()
    return w


def _confirmed_so_predating_revisions(db_session, branch, customer, product,
                                      salesperson=None, wht=None, so_number='2026070001'):
    """Build a CONFIRMED SO directly via the ORM -- bypassing the app's own
    create/confirm routes (and therefore write_revision) entirely -- so no
    SalesOrderRevision row exists for it, exactly the shape of a real order
    that predates the revision-tracking feature."""
    so = SalesOrder(
        branch_id=branch.id, so_number=so_number, order_date=date(2026, 7, 1),
        expected_delivery_date=date(2026, 7, 10),
        customer_id=customer.id, customer_name=customer.name,
        customer_tin=customer.tin, customer_address=customer.address,
        customer_po_number='PO-1001', customer_po_date=date(2026, 6, 28),
        payment_terms='Net 30', reference='REF-1', notes='some notes',
        salesperson_id=salesperson.id if salesperson else None,
        status='confirmed', confirmed_at=None, confirmed_by_id=None,
    )
    db_session.add(so)
    db_session.flush()

    item = SalesOrderItem(
        sales_order_id=so.id, line_number=1, product_id=product.id,
        quantity=Decimal('3000'), unit_price=Decimal('4.20'),
        amount=Decimal('12600.00'), vat_category='VATABLE', vat_rate=Decimal('12.00'),
        wt_id=wht.id if wht else None, line_status='open',
        unit_of_measure_id=product.default_unit_of_measure_id,
        delivery_date=date(2026, 7, 8), delivery_site_id=customer.site.id,
    )
    db_session.add(item)
    db_session.flush()
    item.calculate_amounts()
    so.calculate_totals()
    db_session.commit()
    return so


# ── tests ────────────────────────────────────────────────────────────────────

def test_backfill_creates_rev0_matching_build_snapshot_key_set(
        db_session, branch, customer, product, salesperson, wht):
    so = _confirmed_so_predating_revisions(db_session, branch, customer, product,
                                           salesperson=salesperson, wht=wht)
    assert SalesOrderRevision.query.filter_by(sales_order_id=so.id).count() == 0

    migration = _load_migration()
    migration.op = _bind_op(db_session)
    migration.upgrade()
    db_session.commit()

    rev = SalesOrderRevision.query.filter_by(sales_order_id=so.id, revision_number=0).one()
    assert rev.reason == RECONSTRUCTED

    got = json.loads(rev.snapshot_json)
    expected = build_snapshot(so)

    # Key-set parity with the REAL build_snapshot() output -- revision_view.html
    # renders this exact key set; a missing key is what turned em-dashes and a
    # fabricated "Company Account" into the false document (C1).
    assert set(got['header'].keys()) == set(expected['header'].keys())
    assert len(got['lines']) == 1 == len(expected['lines'])
    assert set(got['lines'][0].keys()) == set(expected['lines'][0].keys())

    # Value-level spot checks on exactly the fields the viewer renders.
    h = got['header']
    assert h['customer_name'] == 'Acme Trading'
    assert h['salesperson_name'] == 'Juan Dela Cruz'
    assert h['subtotal_display'] == '12600.00'
    assert h['total_amount_display'] == '12600.00'
    assert h['status'] == 'confirmed'

    l = got['lines'][0]
    assert l['product_code'] == 'WIDGET'
    assert l['product_name'] == 'Widget'
    assert l['quantity'] == '3000'
    assert l['unit_price_display'] == '4.20'
    assert l['amount_display'] == '12600.00'
    assert l['delivery_site_name'] == 'Main Warehouse'
    assert l['wt_code'] == 'WC160'
    assert l['uom_display'] == 'pcs'
    assert l['line_id'] == so.line_items[0].id


def test_backfill_no_salesperson_or_delivery_site_stays_none_not_falsely_populated(
        db_session, branch, customer, product):
    """No salesperson/delivery site/WT on the order -- the resolved names must
    come back None, never silently borrow another row's data."""
    so = _confirmed_so_predating_revisions(db_session, branch, customer, product,
                                           salesperson=None, wht=None,
                                           so_number='2026070002')
    migration = _load_migration()
    migration.op = _bind_op(db_session)
    migration.upgrade()
    db_session.commit()

    rev = SalesOrderRevision.query.filter_by(sales_order_id=so.id, revision_number=0).one()
    got = json.loads(rev.snapshot_json)
    assert got['header']['salesperson_name'] is None
    assert got['lines'][0]['wt_code'] is None


def test_downgrade_then_upgrade_restores_rev0_for_so_with_later_revision(
        db_session, branch, customer, product):
    """I4: upgrade()'s skip-guard must be the exact inverse of downgrade()'s
    delete predicate. downgrade() deletes only revision_number = 0 rows; if
    upgrade()'s skip check matches on ANY existing revision (not specifically
    rev 0), then downgrade -> re-upgrade permanently strands an order that had
    a later amendment without its Rev 0 -- /revisions/0 404s and the print
    banner's "Supersedes Rev. 0" points at nothing."""
    so = _confirmed_so_predating_revisions(db_session, branch, customer, product,
                                           so_number='2026070003')

    migration = _load_migration()
    migration.op = _bind_op(db_session)
    migration.upgrade()
    db_session.commit()
    assert SalesOrderRevision.query.filter_by(
        sales_order_id=so.id, revision_number=0).first() is not None

    # Simulate a real post-confirm amendment landing a Rev 1 on top of the
    # backfilled Rev 0 (mirrors what app/sales_orders/views.py::amend does).
    write_revision(so, user_id=None, reason='later amendment for this test',
                   authorizing_po=None)
    db_session.commit()
    assert SalesOrderRevision.query.filter_by(sales_order_id=so.id).count() == 2

    # session.commit() releases the connection Operations was bound to (Flask-
    # SQLAlchemy returns it to the pool), so re-bind before each subsequent call
    # -- mirrors how a real `flask db upgrade`/`downgrade` invocation always
    # opens its own fresh connection per command.
    migration.op = _bind_op(db_session)
    migration.downgrade()
    db_session.commit()
    assert SalesOrderRevision.query.filter_by(
        sales_order_id=so.id, revision_number=0).first() is None
    assert SalesOrderRevision.query.filter_by(
        sales_order_id=so.id, revision_number=1).first() is not None

    migration.op = _bind_op(db_session)
    migration.upgrade()
    db_session.commit()
    rev0 = SalesOrderRevision.query.filter_by(
        sales_order_id=so.id, revision_number=0).first()
    assert rev0 is not None, (
        'an order that had a Rev 1 must still get its Rev 0 back on re-upgrade')
    assert rev0.reason == RECONSTRUCTED


def test_upgrade_is_idempotent_on_a_second_run(
        db_session, branch, customer, product):
    so = _confirmed_so_predating_revisions(db_session, branch, customer, product,
                                           so_number='2026070004')
    migration = _load_migration()
    migration.op = _bind_op(db_session)
    migration.upgrade()
    db_session.commit()
    migration.op = _bind_op(db_session)
    migration.upgrade()
    db_session.commit()
    assert SalesOrderRevision.query.filter_by(sales_order_id=so.id).count() == 1
