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


# ── tests ─────────────────────────────────────────────────────────────────────

def test_create_sales_order_persists_and_audits(client, db_session, admin_user, main_branch):
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'description': 'Widget', 'quantity': '2', 'unit_price': '100.00',
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
    """GET /sales-orders/<id> → 200; SO number, line description, and amount render."""
    c = _customer(db_session)
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
        description='Blue Widget',
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
    assert b'Blue Widget' in resp.data
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
