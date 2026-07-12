"""Regression test for BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS (Sales Invoice).

Unlike JV (a pure system sequence, fixed with a silent auto-retry -- see
test_jv_number_race.py), invoice_number is a user-editable field meant to mirror a
physical pre-printed serial (no `readonly` on the form field). A collision must be
SURFACED, not silently resolved: the create must re-render the form with a freshly
suggested number and an explanatory flash, WITHOUT committing anything -- never
silently substitute a number the user may have deliberately typed.

See docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md and the browser-level
repro clients/cas/ui-tests/concurrency_si_concurrent_create.py.
"""
import json
import re
from datetime import date, timedelta

import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.sales_invoices.views import generate_invoice_number
from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.integration, pytest.mark.sales_invoices]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _revenue_account(db_session):
    a = Account.query.filter_by(code='40101').first()
    if not a:
        a = Account(code='40101', name='Service Revenue', account_type='Income',
                    normal_balance='credit', is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def _ar_account(db_session):
    """Matches assign_control_accounts()'s default ar_trade code (10201) so
    _post_invoice_je can resolve it -- SI builds its JE immediately on create."""
    a = Account.query.filter_by(code='10201').first()
    if not a:
        a = Account(code='10201', name='Accounts Receivable - Trade', account_type='Asset',
                    normal_balance='debit', is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def _customer(db_session):
    c = Customer.query.filter_by(code='RACE1').first()
    if not c:
        c = Customer(code='RACE1', name='Race Test Customer', is_active=True)
        db_session.add(c)
        db_session.commit()
    return c


def _payload(invoice_number, customer_id, revenue_account_id, notes):
    return {
        'invoice_number': invoice_number,
        'invoice_date': date.today().isoformat(),
        'due_date': (date.today() + timedelta(days=30)).isoformat(),
        'customer_id': str(customer_id),
        'payment_terms': 'Net 30',
        'notes': notes,
        'line_items': json.dumps([{
            'description': notes, 'amount': '1000.00',
            'quantity': None, 'unit_price': None, 'uom_id': None, 'uom_text': None,
            'product_id': None, 'vat_category': '', 'account_id': revenue_account_id,
            'wt_id': None,
        }]),
    }


def test_collision_reprompts_with_a_fresh_number_instead_of_losing_the_submission(
        client, db_session, accountant_user, main_branch):
    assign_control_accounts(db_session)
    revenue = _revenue_account(db_session)
    _ar_account(db_session)
    cust = _customer(db_session)
    _login(client, accountant_user, main_branch)

    taken_number = generate_invoice_number()
    winner = SalesInvoice(
        branch_id=main_branch.id, invoice_number=taken_number,
        invoice_date=date.today(), due_date=date.today() + timedelta(days=30),
        customer_id=cust.id, customer_name=cust.name, notes='concurrent winner',
        status='draft', amount_paid=0, balance=0,
    )
    db.session.add(winner)
    db.session.commit()

    resp = client.post('/sales-invoices/create',
                        data=_payload(taken_number, cust.id, revenue.id, 'race loser attempt'),
                        follow_redirects=False)

    assert resp.status_code == 200, (
        f"a numbering collision must re-render the form (200), not redirect as if it "
        f"succeeded or silently vanish (got {resp.status_code})"
    )
    loser = SalesInvoice.query.filter_by(notes='race loser attempt').first()
    assert loser is None, "the colliding submission must NOT be silently committed"

    html = resp.get_data(as_text=True)
    m = re.search(r'name="invoice_number"[^>]*value="([^"]*)"', html)
    assert m, "the re-rendered form must still carry the invoice_number field"
    fresh_number = m.group(1)
    assert fresh_number != taken_number, (
        "the re-rendered form must show a FRESH suggested number, not the stale one "
        "that just collided"
    )
    assert 'already' in html.lower() or 'taken' in html.lower(), (
        "the user needs an explanation, not a silent re-render"
    )

    # Resubmitting with the freshly suggested number must succeed cleanly.
    resp2 = client.post('/sales-invoices/create',
                         data=_payload(fresh_number, cust.id, revenue.id, 'race loser attempt'),
                         follow_redirects=False)
    assert resp2.status_code == 302
    saved = SalesInvoice.query.filter_by(notes='race loser attempt').first()
    assert saved is not None
    assert saved.invoice_number == fresh_number
