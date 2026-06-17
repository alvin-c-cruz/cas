"""Integration tests for the APV print page (peso summary + signatories)."""
import pytest
from decimal import Decimal
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.utils import ph_now

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _vendor(db_session):
    v = Vendor(code='V001', name='Acme Supplies',
               check_payee_name='Acme Supplies', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def _expense_account(db_session):
    a = Account(code='60101', name='Office Supplies', account_type='Expense',
                normal_balance='debit', is_active=True)
    db_session.add(a); db_session.commit()
    return a


@pytest.fixture
def _posted_ap(db_session, main_branch, admin_user, accountant_user,
               _vendor, _expense_account):
    today = ph_now().date()
    bill = AccountsPayable(
        ap_number='APV-PRINT-1', vendor_id=_vendor.id, vendor_name=_vendor.name,
        vendor_tin='123-456-789', branch_id=main_branch.id,
        ap_date=today, due_date=today, payment_terms='Net 30',
        status='posted', created_by_id=admin_user.id, posted_by_id=accountant_user.id,
        posted_at=ph_now(),
        subtotal=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        total_before_wt=Decimal('11200.00'),
        withholding_tax_rate=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('11200.00'), amount_paid=Decimal('0.00'),
        balance=Decimal('11200.00'),
    )
    db_session.add(bill); db_session.flush()
    item = AccountsPayableItem(
        ap_id=bill.id, line_number=1, description='Test Service',
        amount=Decimal('11200.00'), vat_category='VATABLE', vat_rate=Decimal('12.00'),
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=_expense_account.id,
    )
    db_session.add(item); db_session.commit()
    return bill


class TestApvPrintContent:
    def test_peso_on_summary_headline_figures(self, client, db_session, admin_user, _posted_ap):
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert '₱11,200.00' in html      # Gross Amount + Net Amount Payable
        assert '₱10,000.00' in html      # Net of VAT (11200 - 1200)

    def test_no_peso_on_vat_rows(self, client, db_session, admin_user, _posted_ap):
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert '₱1,200.00' not in html   # Less/Add Input VAT rows stay unsigned

    def test_signatory_labels(self, client, db_session, admin_user, _posted_ap):
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert 'CHECKED BY' in html
        assert 'REVIEWED BY' not in html
        assert 'Signature over Printed Name' in html

    def test_signatory_names(self, client, db_session, admin_user, _posted_ap):
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert 'Admin User' in html        # created_by.full_name -> Prepared
        assert 'Accountant User' in html   # posted_by.full_name  -> Approved

    def test_draft_approved_box_blank(self, client, db_session, admin_user, _posted_ap):
        _posted_ap.status = 'draft'
        _posted_ap.posted_by_id = None
        db_session.commit()
        login(client)
        html = client.get(f'/accounts-payable/{_posted_ap.id}/print').data.decode()
        assert 'Admin User' in html            # Prepared still shows
        assert 'Accountant User' not in html   # Approved blank on a draft
