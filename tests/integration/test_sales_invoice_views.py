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


class TestListCustomerFilter:
    """The customer filter <select> and export links submit `customer_id`; the list
    query must honor that param (regression: it read `customer` and silently no-op'd)."""

    def test_customer_filter_narrows_list(self, client, db_session,
                                          accountant_user, main_branch):
        c1 = make_customer(db_session, code='SCF1', name='Alpha Buyer')
        c2 = make_customer(db_session, code='SCF2', name='Beta Buyer')
        make_invoice(db_session, c1, main_branch, 'SI-CF-001')
        make_invoice(db_session, c2, main_branch, 'SI-CF-002')

        login(client, username='accountant', password='accountant123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        body = client.get(f'/sales-invoices?customer_id={c1.id}').data.decode()

        assert 'SI-CF-001' in body, "selected customer's invoice should be shown"
        assert 'SI-CF-002' not in body, "other customer's invoice must be filtered out"

    def test_filtered_empty_list_has_no_clear_filters_button(self, client, db_session,
                                                             accountant_user, main_branch):
        """With a filter applied that matches nothing, the empty state shows the
        'no match' message but NOT a 'Clear Filters' button (removed per request)."""
        login(client, username='accountant', password='accountant123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        body = client.get('/sales-invoices?customer_id=999999').data.decode()
        assert 'No invoices match your filters' in body   # we are in the filtered-empty branch
        assert 'Clear Filters' not in body                # ...without the removed button

    def test_csv_export_respects_customer_filter(self, client, db_session,
                                                 accountant_user, main_branch):
        c1 = make_customer(db_session, code='SCF3', name='Gamma Buyer')
        c2 = make_customer(db_session, code='SCF4', name='Delta Buyer')
        make_invoice(db_session, c1, main_branch, 'SI-CF-101')
        make_invoice(db_session, c2, main_branch, 'SI-CF-102')

        login(client, username='accountant', password='accountant123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        body = client.get(f'/sales-invoices/export/csv?customer_id={c1.id}').data.decode()

        assert 'SI-CF-101' in body
        assert 'SI-CF-102' not in body, "CSV export must honor the customer filter"


class TestExportRoleGate:
    """Export/print of the SI list (customer names, TINs, amounts) is staff+ only;
    viewers keep the on-screen list but cannot bulk-export."""

    def _login_viewer(self, client, db_session, viewer_user, main_branch):
        viewer_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='viewer', password='viewer123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

    def test_viewer_blocked_from_csv_export(self, client, db_session,
                                            viewer_user, main_branch):
        self._login_viewer(client, db_session, viewer_user, main_branch)
        resp = client.get('/sales-invoices/export/csv', follow_redirects=False)
        assert resp.status_code == 302
        # role gate redirects to the dashboard root; NOT /login or /select-branch
        assert resp.headers.get('Location') == '/'

    def test_viewer_blocked_from_excel_export(self, client, db_session,
                                              viewer_user, main_branch):
        self._login_viewer(client, db_session, viewer_user, main_branch)
        resp = client.get('/sales-invoices/export/excel', follow_redirects=False)
        assert resp.status_code == 302
        # role gate redirects to the dashboard root; NOT /login or /select-branch
        assert resp.headers.get('Location') == '/'

    def test_viewer_blocked_from_print(self, client, db_session,
                                       viewer_user, main_branch):
        self._login_viewer(client, db_session, viewer_user, main_branch)
        resp = client.get('/sales-invoices/print', follow_redirects=False)
        assert resp.status_code == 302
        # role gate redirects to the dashboard root; NOT /login or /select-branch
        assert resp.headers.get('Location') == '/'

    def test_staff_can_export_csv(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='staff', password='staff123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get('/sales-invoices/export/csv', follow_redirects=False)
        assert resp.status_code == 200
