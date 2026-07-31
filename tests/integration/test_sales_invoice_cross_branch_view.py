"""Viewing a Sales Invoice follows branch ACCESS; modifying it follows the
SELECTED branch.

The combined AR aging report links to invoices in branches other than the one
currently selected, so `view` cannot keep using the selected-branch guard. The
write actions must NOT be loosened with it, and the detail template must not
render controls that would 404 -- a route guard and its template's parallel
guard drifting apart is a known failure mode in this codebase.
"""
import pytest
from decimal import Decimal
from datetime import date

from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.integration]


def _login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def _set_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _invoice(db_session, branch_id, number, status='draft'):
    c = Customer(code=f'X{number}', name=f'Cust {number}', is_active=True)
    db_session.add(c)
    db_session.commit()
    inv = SalesInvoice(
        branch_id=branch_id, invoice_number=number,
        invoice_date=date(2025, 11, 1), due_date=date(2025, 12, 1),
        customer_id=c.id, customer_name=c.name, notes='', status=status,
        amount_paid=Decimal('0.00'), balance=Decimal('100.00'),
        total_amount=Decimal('100.00'), subtotal=Decimal('100.00'),
        vat_amount=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


class TestCrossBranchView:

    def test_entitled_user_can_view_off_branch_invoice(self, client, db_session,
                                                      admin_user, main_branch,
                                                      branch_manila):
        inv = _invoice(db_session, branch_manila.id, 'SI-X1')
        _login(client)
        _set_branch(client, main_branch.id)
        r = client.get(f'/sales-invoices/{inv.id}')
        assert r.status_code == 200

    def test_unentitled_user_gets_404(self, client, db_session, staff_user,
                                      main_branch, branch_manila):
        inv = _invoice(db_session, branch_manila.id, 'SI-X2')
        staff_user.set_branches([main_branch])
        db_session.commit()
        _login(client, username=staff_user.username, password='staff123')
        _set_branch(client, main_branch.id)
        r = client.get(f'/sales-invoices/{inv.id}')
        assert r.status_code == 404

    def test_off_branch_view_hides_write_actions(self, client, db_session,
                                                admin_user, main_branch,
                                                branch_manila):
        inv = _invoice(db_session, branch_manila.id, 'SI-X3', status='draft')
        _login(client)
        _set_branch(client, main_branch.id)
        body = client.get(f'/sales-invoices/{inv.id}').data.decode()
        assert f'/sales-invoices/{inv.id}/edit' not in body
        assert 'Post Invoice' not in body
        assert 'Void Invoice' not in body

    def test_same_branch_view_still_shows_write_actions(self, client, db_session,
                                                       admin_user, main_branch):
        inv = _invoice(db_session, main_branch.id, 'SI-X4', status='draft')
        _login(client)
        _set_branch(client, main_branch.id)
        body = client.get(f'/sales-invoices/{inv.id}').data.decode()
        assert f'/sales-invoices/{inv.id}/edit' in body
        assert 'Post Invoice' in body

    def test_edit_still_blocked_off_branch(self, client, db_session, admin_user,
                                           main_branch, branch_manila):
        """The write guard must NOT be loosened along with the read guard."""
        inv = _invoice(db_session, branch_manila.id, 'SI-X5', status='draft')
        _login(client)
        _set_branch(client, main_branch.id)
        assert client.get(f'/sales-invoices/{inv.id}/edit').status_code == 404
