"""Integration tests for the AR Aging report."""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.integration]


# ── Helpers ──────────────────────────────────────────────────────────────────

def login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def set_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def make_customer(db_session, code='C001'):
    c = Customer(
        code=code,
        name=f'Customer {code}',
        is_active=True,
    )
    db_session.add(c)
    db_session.commit()
    return c


def make_invoice(db_session, customer, branch_id, status, balance,
                 due_days_ago=0, invoice_number=None):
    today = date.today()
    inv = SalesInvoice(
        branch_id=branch_id,
        invoice_number=invoice_number or f'SI-{status[:3].upper()}-001',
        invoice_date=today,
        due_date=today - timedelta(days=due_days_ago),
        customer_id=customer.id,
        customer_name=customer.name,
        notes='',
        status=status,
        amount_paid=Decimal('0.00'),
        balance=Decimal(str(balance)),
        total_amount=Decimal(str(balance)),
        subtotal=Decimal(str(balance)),
        vat_amount=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


# ── View tests ───────────────────────────────────────────────────────────────

class TestARAgingView:

    def test_page_loads(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200

    def test_empty_state_no_invoices(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200
        assert b'No outstanding receivables' in r.data

    def test_posted_invoice_with_balance_appears(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='C001')
        make_invoice(db_session, c, main_branch.id, 'posted', 5000,
                     due_days_ago=10, invoice_number='SI-PST-001')
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200
        assert b'5,000.00' in r.data

    def test_partially_paid_invoice_appears(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='C002')
        make_invoice(db_session, c, main_branch.id, 'partially_paid', 3000,
                     due_days_ago=5, invoice_number='SI-PAR-001')
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200
        assert b'3,000.00' in r.data

    def test_paid_invoice_does_not_appear(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='C003')
        make_invoice(db_session, c, main_branch.id, 'paid', 0,
                     invoice_number='SI-PAI-001')
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200
        assert b'SI-PAI-001' not in r.data

    def test_draft_invoice_does_not_appear(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='C004')
        make_invoice(db_session, c, main_branch.id, 'draft', 2000,
                     invoice_number='SI-DFT-001')
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200
        assert b'SI-DFT-001' not in r.data

    def test_voided_invoice_does_not_appear(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='C005')
        make_invoice(db_session, c, main_branch.id, 'voided', 1500,
                     invoice_number='SI-VOI-001')
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200
        assert b'SI-VOI-001' not in r.data

    def test_overdue_invoice_in_1_30_bucket(self, client, db_session, admin_user, main_branch):
        """A posted invoice 15 days overdue should appear (amber coloring in 1-30 column)."""
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='C006')
        make_invoice(db_session, c, main_branch.id, 'posted', 1500,
                     due_days_ago=15, invoice_number='SI-AGE-001')
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200
        assert b'1,500.00' in r.data

    def test_as_of_date_filter(self, client, db_session, admin_user, main_branch):
        """Invoices with balance > 0 and status posted appear regardless of as_of_date."""
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='C007')
        make_invoice(db_session, c, main_branch.id, 'posted', 8000,
                     due_days_ago=0, invoice_number='SI-ASF-001')
        r = client.get('/reports/ar-aging?as_of=2030-01-01')
        assert r.status_code == 200
        assert b'8,000.00' in r.data

    def test_invalid_as_of_date_falls_back_to_today(self, client, db_session, admin_user, main_branch):
        """A malformed as_of query param should not crash — falls back to today."""
        login(client)
        set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging?as_of=not-a-date')
        assert r.status_code == 200

    def test_invoice_number_links_to_si_detail(self, client, db_session, admin_user, main_branch):
        """Template renders an anchor with href to sales_invoices.view for each invoice."""
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='C008')
        inv = make_invoice(db_session, c, main_branch.id, 'posted', 2500,
                           due_days_ago=5, invoice_number='SI-LNK-001')
        r = client.get('/reports/ar-aging')
        assert r.status_code == 200
        assert f'/sales-invoices/{inv.id}'.encode() in r.data


# ── Export tests ─────────────────────────────────────────────────────────────

class TestARAgingExport:

    def test_excel_export_returns_file(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging/export/excel')
        assert r.status_code == 200
        content_type = r.headers.get('Content-Type', '')
        assert (
            'spreadsheet' in content_type
            or 'excel' in content_type
            or 'octet-stream' in content_type
        )

    def test_csv_export_returns_file(self, client, db_session, admin_user, main_branch):
        login(client)
        set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging/export/csv')
        assert r.status_code == 200
        content_type = r.headers.get('Content-Type', '')
        assert (
            'csv' in content_type
            or 'text/plain' in content_type
            or 'octet-stream' in content_type
        )

    def test_excel_export_has_xlsx_magic_bytes(self, client, db_session, admin_user, main_branch):
        """xlsx files start with PK (zip magic bytes 50 4B)."""
        login(client)
        set_branch(client, main_branch.id)
        c = make_customer(db_session, code='CE01')
        make_invoice(db_session, c, main_branch.id, 'posted', 1000,
                     due_days_ago=0, invoice_number='SI-XLS-001')
        r = client.get('/reports/ar-aging/export/excel')
        assert r.status_code == 200
        assert r.data[:2] == b'PK'

    def test_csv_export_contains_headers(self, client, db_session, admin_user, main_branch):
        """CSV response body should contain the header columns."""
        login(client)
        set_branch(client, main_branch.id)
        r = client.get('/reports/ar-aging/export/csv')
        assert r.status_code == 200
        body = r.data.decode('utf-8', errors='replace')
        assert 'Invoice #' in body or 'Customer' in body


# ── Builder unit tests ────────────────────────────────────────────────────────

class TestARAgingBuilder:
    """Direct tests for the _build_ar_aging_data private builder function."""

    def test_builder_empty_returns_empty(self, client, db_session, admin_user, main_branch):
        """With no invoices, builder returns empty list and zero grand totals."""
        from app.reports.views import _build_ar_aging_data
        customers_list, grand_totals = _build_ar_aging_data(date.today(), main_branch.id)
        assert customers_list == []
        for key in ('current', '1-30', '31-60', '61-90', '90+', 'total'):
            assert grand_totals[key] == Decimal('0.00'), f"Expected 0 for {key}"

    def test_builder_buckets_correct(self, client, db_session, admin_user, main_branch):
        """Builder places invoices into the correct aging buckets."""
        from app.reports.views import _build_ar_aging_data
        c = make_customer(db_session, code='BLD-C001')
        inv_current = make_invoice(db_session, c, main_branch.id, 'posted', 1000,
                                   due_days_ago=0, invoice_number='SI-BLD-CUR')
        inv_overdue = make_invoice(db_session, c, main_branch.id, 'posted', 2000,
                                   due_days_ago=45, invoice_number='SI-BLD-45D')
        customers_list, grand_totals = _build_ar_aging_data(date.today(), main_branch.id)
        assert len(customers_list) == 1
        entry = customers_list[0]
        assert entry['31-60'] == Decimal('2000.00')
        assert entry['current'] == Decimal('1000.00')
        assert grand_totals['31-60'] == Decimal('2000.00')
        assert grand_totals['current'] == Decimal('1000.00')

    def test_builder_grand_totals_reconcile(self, client, db_session, admin_user, main_branch):
        """Sum of all per-customer totals equals grand_totals['total']."""
        from app.reports.views import _build_ar_aging_data
        c1 = make_customer(db_session, code='BLD-C002')
        c2 = make_customer(db_session, code='BLD-C003')
        make_invoice(db_session, c1, main_branch.id, 'posted', 1500,
                     due_days_ago=5, invoice_number='SI-REC-001')
        make_invoice(db_session, c2, main_branch.id, 'posted', 2500,
                     due_days_ago=35, invoice_number='SI-REC-002')
        customers_list, grand_totals = _build_ar_aging_data(date.today(), main_branch.id)
        customer_total_sum = sum(c['total'] for c in customers_list)
        assert customer_total_sum == grand_totals['total']

    def test_builder_sorted_by_total_desc(self, client, db_session, admin_user, main_branch):
        """Builder returns customers sorted by total descending."""
        from app.reports.views import _build_ar_aging_data
        c1 = make_customer(db_session, code='BLD-C004')
        c2 = make_customer(db_session, code='BLD-C005')
        make_invoice(db_session, c1, main_branch.id, 'posted', 500,
                     due_days_ago=0, invoice_number='SI-SRT-001')
        make_invoice(db_session, c2, main_branch.id, 'posted', 3000,
                     due_days_ago=0, invoice_number='SI-SRT-002')
        customers_list, grand_totals = _build_ar_aging_data(date.today(), main_branch.id)
        assert len(customers_list) == 2
        assert customers_list[0]['total'] >= customers_list[1]['total']
        assert customers_list[0]['name'] == c2.name
