"""Integration tests — Sales Orders create/edit, uniqueness, audit."""
import json
import datetime
import pytest
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.customers.models import Customer
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def sales_orders_module_enabled(db_session):
    """Enable the optional sales_orders module for all SO tests."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


# ── helpers ──────────────────────────────────────────────────────────────────

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _customer(db_session):
    c = Customer(code='ACME01', name='Acme', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _product(db_session, code='WIDGET', name='Widget'):
    from app.units_of_measure.models import UnitOfMeasure
    from app.products.models import Product
    uom = UnitOfMeasure.query.filter_by(code='pcs').first()
    if uom is None:
        uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
        db_session.add(uom); db_session.commit()
    p = Product(code=code, name=name, default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('100.00'), is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _enable_products(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    AppSettings.set_setting('module_enabled:products', '1')
    db_session.commit()
    clear_module_config_cache()


# ── tests ─────────────────────────────────────────────────────────────────────

def test_create_sales_order_persists_and_audits(client, db_session, admin_user, main_branch):
    c = _customer(db_session)
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0001', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0001').first()
    assert so is not None
    assert so.status == 'draft'
    assert so.total_amount == Decimal('200.00')
    # no journal entry — SalesOrder is operational only
    assert not hasattr(so, 'journal_entry_id') or so.journal_entry_id is None
    assert AuditLog.query.filter_by(module='sales_orders', action='create').count() >= 1


def test_detail_view_no_entity_leak_and_no_currency_glyph(client, db_session, admin_user, main_branch):
    """SO detail must render em-dashes as the literal glyph (never the '&#8212;'
    entity, which Jinja autoescaping leaks as literal text when it sits inside a
    {{ }} string fallback), and must show bare numbers with no peso glyph
    (no-currency-symbol convention). A line with no UOM exercises the em-dash
    fallback; a unit price exercises the money cells."""
    c = _customer(db_session)
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
    client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0009', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0009').first()
    html = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)
    assert '&#8212;' not in html          # em-dash entity (leaks or clutters — use the glyph)
    assert '₱' not in html           # peso sign U+20B1


def test_line_without_product_is_rejected(client, db_session, admin_user, main_branch):
    """A real line (amount > 0) with no product must be rejected server-side and the
    SO must not persist — product is required per line."""
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': None, 'quantity': '1', 'unit_price': '50.00',
                         'vat_category': None, 'vat_rate': '0'}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0100', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'select a product' in resp.data
    assert SalesOrder.query.filter_by(so_number='SO-2026-06-0100').first() is None


def test_create_form_renders_so_number_and_line_editor(client, db_session, admin_user, main_branch):
    """GET /sales-orders/create → 200; full editor present (so_number editable, line table, add-line btn)."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    # editable so_number input
    assert b'so_number' in resp.data
    # line-item editor markers
    assert b'lineItemsTable' in resp.data
    assert b'lineItemsBody' in resp.data
    assert b'lineItemsData' in resp.data
    assert b'addLineBtn' in resp.data


def test_duplicate_so_number_rejected(client, db_session, admin_user, main_branch):
    import datetime
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    db.session.add(SalesOrder(
        so_number='SO-DUP',
        order_date=datetime.date.today(),
        customer_id=c.id,
        customer_name='Acme',
        branch_id=main_branch.id,
    ))
    db.session.commit()
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-DUP', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme',
        'payment_terms': 'Net 30',
        'notes': '', 'line_items': '[]'}, follow_redirects=True)
    # must not create a second SO with the same number
    assert SalesOrder.query.filter_by(so_number='SO-DUP').count() == 1


def test_view_sales_order_detail(client, db_session, admin_user, main_branch):
    """GET /sales-orders/<id> → 200; SO number, line product, and amount render."""
    c = _customer(db_session)
    p = _product(db_session, code='BLUE', name='Blue Widget')
    _enable_products(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    so = SalesOrder(
        so_number='SO-VIEW-0001',
        order_date=datetime.date(2026, 6, 28),
        customer_id=c.id,
        customer_name='Acme',
        branch_id=main_branch.id,
        status='draft',
    )
    db_session.add(so)
    db_session.flush()

    line = SalesOrderItem(
        sales_order_id=so.id,
        line_number=1,
        product_id=p.id,
        quantity=Decimal('3.0000'),
        unit_price=Decimal('50.00'),
        amount=Decimal('150.00'),
        vat_rate=Decimal('0.00'),
        line_total=Decimal('150.00'),
        vat_amount=Decimal('0.00'),
    )
    so.line_items.append(line)
    so.calculate_totals()
    db_session.commit()

    resp = client.get(f'/sales-orders/{so.id}')
    assert resp.status_code == 200
    assert b'SO-VIEW-0001' in resp.data
    assert b'Blue Widget' in resp.data   # product name renders in the line
    assert b'150' in resp.data  # amount appears in the line


def test_list_shows_so_number_and_status_badge(client, db_session, admin_user, main_branch):
    """GET /sales-orders → 200; SO number and draft status badge appear in the list."""
    import datetime
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    # Create one SO directly in the DB (branch-scoped)
    so = SalesOrder(
        so_number='SO-2026-06-LIST1',
        order_date=datetime.date(2026, 6, 28),
        customer_id=c.id,
        customer_name='Acme',
        branch_id=main_branch.id,
        status='draft',
    )
    db_session.add(so)
    db_session.commit()

    resp = client.get('/sales-orders')
    assert resp.status_code == 200
    assert b'SO-2026-06-LIST1' in resp.data
    # Status badge renders the text "Draft"
    assert b'badge-draft' in resp.data
    assert b'Draft' in resp.data
