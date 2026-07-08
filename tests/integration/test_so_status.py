"""Integration tests: Sales Order confirm + cancel status actions (Task 8).

Tests:
1. Draft SO confirmed → status='confirmed', audit row exists.
2. Confirming creates NO JournalEntry.
3. Confirmed SO cancelled with a reason → status='cancelled', cancel_reason persisted, audit row.
4. Editing a confirmed SO is blocked (redirects, status unchanged).
"""
import pytest
from datetime import date
from decimal import Decimal

from app import db

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def sales_orders_module_enabled(db_session):
    """Sales Orders is now an optional, default-off module — enable it for these
    route tests (mirrors the autouse fixture in test_sales_orders_crud.py)."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


# ── helpers (pasted from test_sales_invoices.py pattern) ────────────────────

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def customer(db_session):
    from app.customers.models import Customer
    c = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def draft_so(db_session, main_branch, customer, accountant_user):
    from app.sales_orders.models import SalesOrder
    so = SalesOrder(
        branch_id=main_branch.id,
        so_number='SO-2026-06-0001',
        order_date=date(2026, 6, 28),
        customer_id=customer.id,
        customer_name=customer.name,
        notes='',
        status='draft',
        subtotal=Decimal('11200.00'),
        vat_amount=Decimal('1200.00'),
        total_amount=Decimal('11200.00'),
        created_by_id=accountant_user.id,
    )
    db_session.add(so)
    db_session.commit()
    return so


# ── tests ─────────────────────────────────────────────────────────────────────

def test_confirm_so_sets_status_and_audit(client, db_session, main_branch,
                                          accountant_user, draft_so):
    """POST confirm on a draft SO → status='confirmed' + an audit row for the confirm."""
    from app.sales_orders.models import SalesOrder
    from app.audit.models import AuditLog

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    resp = client.post(f'/sales-orders/{draft_so.id}/confirm', follow_redirects=False)
    assert resp.status_code == 302

    so = db.session.get(SalesOrder, draft_so.id)
    assert so.status == 'confirmed'
    assert so.confirmed_by_id == accountant_user.id
    assert so.confirmed_at is not None

    audit = AuditLog.query.filter_by(
        module='sales_orders', action='update', record_id=so.id
    ).first()
    assert audit is not None, 'Audit row must exist after confirm'
    assert audit.notes == 'Confirmed'


def test_confirm_creates_no_journal_entry(client, db_session, main_branch,
                                          accountant_user, draft_so):
    """Confirming an SO must NOT create any JournalEntry — SO posts nothing."""
    from app.journal_entries.models import JournalEntry

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    resp = client.post(f'/sales-orders/{draft_so.id}/confirm', follow_redirects=False)
    assert resp.status_code == 302
    assert JournalEntry.query.count() == 0


def test_cancel_so_sets_status_reason_and_audit(client, db_session, main_branch,
                                                 accountant_user, draft_so):
    """POST cancel on a confirmed SO → status='cancelled', reason persisted, audit row."""
    from app.sales_orders.models import SalesOrder
    from app.audit.models import AuditLog

    # Promote to confirmed first
    draft_so.status = 'confirmed'
    db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    reason = 'Customer changed their mind and withdrew the order'
    resp = client.post(f'/sales-orders/{draft_so.id}/cancel',
                       data={'cancel_reason': reason},
                       follow_redirects=False)
    assert resp.status_code == 302

    so = db.session.get(SalesOrder, draft_so.id)
    assert so.status == 'cancelled'
    assert so.cancel_reason == reason
    assert so.cancelled_by_id == accountant_user.id
    assert so.cancelled_at is not None

    audit = AuditLog.query.filter_by(
        module='sales_orders', action='update', record_id=so.id
    ).first()
    assert audit is not None, 'Audit row must exist after cancel'
    assert 'Cancelled' in audit.notes


def test_edit_confirmed_so_is_blocked(client, db_session, main_branch,
                                       accountant_user, draft_so):
    """GET/POST /edit on a confirmed SO → redirect, status unchanged."""
    from app.sales_orders.models import SalesOrder

    draft_so.status = 'confirmed'
    db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    # GET the edit page — must redirect away
    resp = client.get(f'/sales-orders/{draft_so.id}/edit', follow_redirects=False)
    assert resp.status_code == 302

    # Status must still be confirmed
    so = db.session.get(SalesOrder, draft_so.id)
    assert so.status == 'confirmed'
