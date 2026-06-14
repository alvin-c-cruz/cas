"""Integration tests for sales invoice branch scoping."""
import pytest
from decimal import Decimal

from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.utils import ph_now
pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]




def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_customer(db_session, code='SC001', name='Test Customer'):
    c = Customer(code=code, name=name, is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def make_invoice(db_session, customer, branch, invoice_number, status='draft'):
    today = ph_now().date()
    inv = SalesInvoice(
        invoice_number=invoice_number,
        invoice_date=today,
        due_date=today,
        customer_id=customer.id,
        customer_name=customer.name,
        branch_id=branch.id,
        status=status,
        subtotal=Decimal('1000.00'),
        vat_amount=Decimal('0.00'),
        total_amount=Decimal('1000.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('1000.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


class TestBranchScoping:
    def test_cross_branch_detail_returns_404(self, client, db_session,
                                             viewer_user, main_branch, branch_manila):
        customer = make_customer(db_session)
        main_inv = make_invoice(db_session, customer, main_branch, 'SI-001')
        other_inv = make_invoice(db_session, customer, branch_manila, 'SI-002')

        viewer_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='viewer', password='viewer123')

        resp = client.get(f'/sales-invoices/{main_inv.id}')
        assert resp.status_code == 200

        resp = client.get(f'/sales-invoices/{other_inv.id}')
        assert resp.status_code == 404

    def test_cross_branch_edit_returns_404(self, client, db_session,
                                           accountant_user, main_branch, branch_manila):
        customer = make_customer(db_session, code='SC002', name='Test Customer 2')
        other_inv = make_invoice(db_session, customer, branch_manila, 'SI-011')

        login(client, username='accountant', password='accountant123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        resp = client.get(f'/sales-invoices/{other_inv.id}/edit')
        assert resp.status_code == 404
