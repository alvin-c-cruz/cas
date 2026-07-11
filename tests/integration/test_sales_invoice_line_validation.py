"""Server-side line-item validation for Sales Invoice create/edit (FINDING-1).

The create form disables Save client-side when there is no valid line, but the
server accepted an empty/zero line (blank description + 0.00 amount), persisting
a zero-total junk draft. These tests pin the server-side guard.
"""
import json as _json

import pytest

from app.accounts.models import Account
from app.sales_invoices.models import SalesInvoice


@pytest.fixture
def customer(db_session):
    from app.customers.models import Customer
    c = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if not b:
        b = Branch(name='Main Branch', code='MB', is_active=True)
        db_session.add(b)
        db_session.commit()
    return b


def _ensure_gl_accounts(db_session):
    for code, name, typ, nb in [
        ('10201', 'AR - Trade', 'Asset', 'debit'),
        ('20201', 'Output VAT', 'Liability', 'credit'),
        ('10212', 'Creditable WHT Receivable', 'Asset', 'debit'),
    ]:
        if not Account.query.filter_by(code=code).first():
            db_session.add(Account(code=code, name=name, account_type=typ,
                                   normal_balance=nb, is_active=True))
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(user.id)


def _post_create(client, customer, line_items, notes='Test particulars'):
    return client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-2026-9001',
        'invoice_date': '2026-06-20',
        'due_date': '2026-07-20',
        'customer_id': str(customer.id),
        'payment_terms': 'Net 30',
        'notes': notes,
        'line_items': _json.dumps(line_items),
    })


def test_create_rejects_blank_description_zero_amount_line(
        client, db_session, accountant_user, customer, revenue_account, branch):
    """A single empty line (blank description + 0.00 amount) must not create an invoice."""
    _ensure_gl_accounts(db_session)
    _login(client, accountant_user, branch)

    resp = _post_create(client, customer, [
        {'description': '', 'amount': '0', 'vat_category': '',
         'wt_id': '', 'account_id': str(revenue_account.id)},
    ])

    assert resp.status_code == 200  # re-render, not a 302 redirect
    assert SalesInvoice.query.count() == 0


def test_create_rejects_zero_amount_line(
        client, db_session, accountant_user, customer, revenue_account, branch):
    """A line with a description but a zero amount must be rejected."""
    _ensure_gl_accounts(db_session)
    _login(client, accountant_user, branch)

    resp = _post_create(client, customer, [
        {'description': 'Consulting', 'amount': '0', 'vat_category': '',
         'wt_id': '', 'account_id': str(revenue_account.id)},
    ])

    assert resp.status_code == 200
    assert SalesInvoice.query.count() == 0


def test_create_accepts_blank_description_with_amount(
        client, db_session, accountant_user, customer, revenue_account, branch):
    """A line carrying an amount but no description is now ALLOWED — the header Notes
    (Particulars) replaces the per-line description as the particulars source."""
    _ensure_gl_accounts(db_session)
    _login(client, accountant_user, branch)

    resp = _post_create(client, customer, [
        {'description': '   ', 'amount': '11200', 'vat_category': '',
         'wt_id': '', 'account_id': str(revenue_account.id)},
    ])

    assert resp.status_code == 302
    assert SalesInvoice.query.count() == 1


def test_create_rejects_no_line_items(
        client, db_session, accountant_user, customer, revenue_account, branch):
    """Submitting with no line items at all must be rejected."""
    _ensure_gl_accounts(db_session)
    _login(client, accountant_user, branch)

    resp = _post_create(client, customer, [])

    assert resp.status_code == 200
    assert SalesInvoice.query.count() == 0


def test_create_accepts_valid_line(
        client, db_session, accountant_user, customer, revenue_account, branch):
    """A line with a description and a positive amount still creates the invoice."""
    _ensure_gl_accounts(db_session)
    _login(client, accountant_user, branch)

    resp = _post_create(client, customer, [
        {'description': 'Consulting', 'amount': '11200', 'vat_category': '',
         'wt_id': '', 'account_id': str(revenue_account.id)},
    ])

    assert resp.status_code == 302
    assert SalesInvoice.query.count() == 1
