"""Integration tests for the AP Aging report view and export routes."""
import pytest
from datetime import date, timedelta
from decimal import Decimal

from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def login(client, username='accountant', password='accountant123'):
    """POST to the login endpoint."""
    client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def set_branch(client, branch_id):
    """Inject branch selection directly into the session."""
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def make_vendor(db_session, code='APV001', name='AP Test Vendor'):
    """Create a minimal Vendor for foreign-key satisfaction."""
    vendor = Vendor(
        code=code,
        name=name,
        check_payee_name=name,
        is_active=True,
        payment_terms='Net 30',
    )
    db_session.add(vendor)
    db_session.commit()
    return vendor


def make_ap(db_session, vendor, branch_id, ap_number='AP-2026-06-0001',
              status='posted', ap_date=None, due_date=None,
              total_amount=Decimal('1000.00'), balance=None):
    """Create a AccountsPayable with sensible defaults; accepts overrides."""
    today = date.today()
    bill = AccountsPayable(
        ap_number=ap_number,
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_tin='',
        vendor_address='',
        branch_id=branch_id,
        ap_date=ap_date or today,
        due_date=due_date or (today + timedelta(days=30)),
        status=status,
        subtotal=total_amount,
        vat_amount=Decimal('0.00'),
        total_before_wt=total_amount,
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=total_amount,
        amount_paid=Decimal('0.00'),
        balance=balance if balance is not None else total_amount,
        payment_terms='Net 30',
    )
    db_session.add(bill)
    db_session.commit()
    return bill


# ---------------------------------------------------------------------------
# TestAPAgingView
# ---------------------------------------------------------------------------

class TestAPAgingView:
    """Tests for GET /reports/ap-aging."""

    def test_requires_login(self, client, db_session):
        """Unauthenticated request should redirect (302)."""
        resp = client.get('/reports/ap-aging')
        assert resp.status_code == 302

    def test_accountant_can_access(self, client, db_session, accountant_user, main_branch):
        """Authenticated accountant gets a 200 with 'AP Aging' in the body."""
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging')
        assert resp.status_code == 200
        assert b'AP Aging' in resp.data

    def test_empty_state(self, client, db_session, accountant_user, main_branch):
        """No bills → page shows 'No outstanding payables' message."""
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging')
        assert resp.status_code == 200
        assert b'No outstanding payables' in resp.data

    def test_posted_bill_appears(self, client, db_session, accountant_user, main_branch):
        """A posted bill with balance > 0 should show the vendor name."""
        vendor = make_vendor(db_session, code='APV-P001', name='Acme Supplies')
        make_ap(db_session, vendor, main_branch.id,
                  ap_number='AP-2026-01-0001', status='posted',
                  balance=Decimal('5000.00'))
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging')
        assert resp.status_code == 200
        assert b'Acme Supplies' in resp.data

    def test_partially_paid_bill_appears(self, client, db_session, accountant_user, main_branch):
        """A partially_paid bill with balance > 0 should show the vendor name."""
        vendor = make_vendor(db_session, code='APV-PP01', name='Partial Pay Vendor')
        make_ap(db_session, vendor, main_branch.id,
                  ap_number='AP-2026-01-0002', status='partially_paid',
                  total_amount=Decimal('3000.00'),
                  balance=Decimal('1500.00'))
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging')
        assert resp.status_code == 200
        assert b'Partial Pay Vendor' in resp.data

    def test_paid_bill_excluded(self, client, db_session, accountant_user, main_branch):
        """A fully-paid bill should NOT appear in the report."""
        vendor = make_vendor(db_session, code='APV-PAID', name='Fully Paid Vendor')
        make_ap(db_session, vendor, main_branch.id,
                  ap_number='AP-2026-01-0003', status='paid',
                  total_amount=Decimal('2000.00'),
                  balance=Decimal('0.00'))
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging')
        assert resp.status_code == 200
        assert b'Fully Paid Vendor' not in resp.data

    def test_as_of_date_filter_current_bucket(self, client, db_session, accountant_user, main_branch):
        """Bill whose due_date is in the future relative to as_of lands in 'current' bucket."""
        today = date.today()
        vendor = make_vendor(db_session, code='APV-CUR1', name='Current Bucket Vendor')
        # due_date = today + 10 days; as_of = yesterday → not yet overdue
        make_ap(db_session, vendor, main_branch.id,
                  ap_number='AP-2026-02-0001', status='posted',
                  due_date=today + timedelta(days=10),
                  balance=Decimal('1000.00'))
        login(client)
        set_branch(client, main_branch.id)
        as_of = (today - timedelta(days=1)).isoformat()
        resp = client.get(f'/reports/ap-aging?as_of={as_of}')
        assert resp.status_code == 200
        # The template renders the 'current' bucket label for on-time bills
        assert b'Current' in resp.data

    def test_as_of_date_filter_overdue_bucket(self, client, db_session, accountant_user, main_branch):
        """Bill overdue by more than 90 days relative to as_of lands in '90+' bucket."""
        today = date.today()
        vendor = make_vendor(db_session, code='APV-OLD1', name='Old Overdue Vendor')
        # due_date = today; as_of = today + 91 → 91 days overdue → 90+ bucket
        make_ap(db_session, vendor, main_branch.id,
                  ap_number='AP-2026-02-0002', status='posted',
                  due_date=today,
                  balance=Decimal('1000.00'))
        login(client)
        set_branch(client, main_branch.id)
        as_of = (today + timedelta(days=91)).isoformat()
        resp = client.get(f'/reports/ap-aging?as_of={as_of}')
        assert resp.status_code == 200
        # Template renders '90+ Days' label for overdue > 90 days
        assert b'90+ Days' in resp.data

    def test_branch_isolation(self, client, db_session, accountant_user, main_branch, branch_manila):
        """Bills belonging to branch_manila are NOT visible when branch main is selected."""
        vendor = make_vendor(db_session, code='APV-BR01', name='Manila Branch Vendor')
        # Create bill in branch_manila
        make_ap(db_session, vendor, branch_manila.id,
                  ap_number='AP-2026-03-0001', status='posted',
                  balance=Decimal('8000.00'))
        login(client)
        # Select main_branch (not manila)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging')
        assert resp.status_code == 200
        assert b'Manila Branch Vendor' not in resp.data


# ---------------------------------------------------------------------------
# TestAPAgingExport
# ---------------------------------------------------------------------------

class TestAPAgingExport:
    """Tests for the Excel and CSV export routes."""

    def test_excel_export_requires_login(self, client, db_session):
        """Unauthenticated Excel export request should redirect."""
        resp = client.get('/reports/ap-aging/export/excel')
        assert resp.status_code == 302

    def test_csv_export_requires_login(self, client, db_session):
        """Unauthenticated CSV export request should redirect."""
        resp = client.get('/reports/ap-aging/export/csv')
        assert resp.status_code == 302

    def test_excel_export_200(self, client, db_session, accountant_user, main_branch):
        """Authenticated Excel export returns 200 with spreadsheet content-type."""
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging/export/excel')
        assert resp.status_code == 200
        assert 'spreadsheet' in resp.content_type.lower()

    def test_csv_export_200(self, client, db_session, accountant_user, main_branch):
        """Authenticated CSV export returns 200 with text/csv content-type."""
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging/export/csv')
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type.lower()

    def test_excel_export_contains_bill_data(self, client, db_session, accountant_user, main_branch):
        """Excel export includes vendor name from an outstanding posted bill.

        XLSX is a ZIP of XML files; the vendor name lives inside the compressed
        shared-strings XML, not in plaintext.  We unzip and search the raw XML.
        """
        import io
        import zipfile

        vendor = make_vendor(db_session, code='APV-XL01', name='Excel Export Vendor')
        make_ap(db_session, vendor, main_branch.id,
                  ap_number='AP-2026-04-0001', status='posted',
                  balance=Decimal('2500.00'))
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging/export/excel')
        assert resp.status_code == 200

        # Decompress the XLSX (ZIP) and search every XML member for the vendor name
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            found = any(
                b'Excel Export Vendor' in zf.read(name)
                for name in zf.namelist()
            )
        assert found, "Vendor name not found in any XLSX XML part"

    def test_csv_export_contains_bill_data(self, client, db_session, accountant_user, main_branch):
        """CSV export includes vendor name and bill number for outstanding bills."""
        vendor = make_vendor(db_session, code='APV-CSV1', name='CSV Export Vendor')
        make_ap(db_session, vendor, main_branch.id,
                  ap_number='AP-2026-05-0001', status='posted',
                  balance=Decimal('1750.00'))
        login(client)
        set_branch(client, main_branch.id)
        resp = client.get('/reports/ap-aging/export/csv')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'CSV Export Vendor' in body
        assert 'AP-2026-05-0001' in body
