"""Integration tests for receipt branch scoping."""
import pytest
from decimal import Decimal

from app.receipts.models import Receipt
from app.customers.models import Customer
from app.utils import ph_now


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_customer(db_session, code='RC001', name='Receipt Customer'):
    c = Customer(code=code, name=name, is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def make_receipt(db_session, branch, receipt_number, customer=None, status='draft'):
    today = ph_now().date()
    r = Receipt(
        receipt_number=receipt_number,
        receipt_date=today,
        transaction_type='collection',
        payment_method='cash',
        amount=Decimal('1000.00'),
        branch_id=branch.id,
        status=status,
        customer_id=customer.id if customer else None,
        customer_name=customer.name if customer else None,
    )
    db_session.add(r)
    db_session.commit()
    return r


class TestBranchScoping:
    def test_cross_branch_detail_returns_404(self, client, db_session,
                                             viewer_user, main_branch, branch_manila):
        customer = make_customer(db_session)
        main_receipt = make_receipt(db_session, main_branch, 'CR-2026-0001', customer)
        other_receipt = make_receipt(db_session, branch_manila, 'CR-2026-0002', customer)

        viewer_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='viewer', password='viewer123')

        resp = client.get(f'/receipts/{main_receipt.id}')
        assert resp.status_code == 200

        resp = client.get(f'/receipts/{other_receipt.id}')
        assert resp.status_code == 404

    def test_cross_branch_edit_returns_404(self, client, db_session,
                                           accountant_user, main_branch, branch_manila):
        customer = make_customer(db_session, code='RC002', name='Receipt Customer 2')
        other_receipt = make_receipt(db_session, branch_manila, 'CR-2026-0011', customer)

        login(client, username='accountant', password='accountant123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        resp = client.get(f'/receipts/{other_receipt.id}/edit')
        assert resp.status_code == 404
