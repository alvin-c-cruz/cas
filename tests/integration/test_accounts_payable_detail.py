"""Integration tests for the redesigned purchase bill detail page."""
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


def get_or_create_account(db_session, code, name, acct_type, normal_balance):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=acct_type,
                    normal_balance=normal_balance, is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def make_vendor(db_session, code='DV001'):
    v = Vendor(code=code, name='Detail Test Vendor',
               check_payee_name='Detail Test Vendor',
               is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def make_ap_with_line(db_session, vendor, branch, expense_account,
                         vendor_invoice_number=''):
    today = ph_now().date()
    bill = AccountsPayable(
        ap_number='DET-001',
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_tin='123-456-789',
        vendor_address='Test Address, Manila',
        branch_id=branch.id,
        ap_date=today,
        due_date=today,
        payment_terms='Net 30',
        vendor_invoice_number=vendor_invoice_number,
        status='draft',
        subtotal=Decimal('11200.00'),
        vat_amount=Decimal('1200.00'),
        total_before_wt=Decimal('11200.00'),
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('11200.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('11200.00'),
    )
    db_session.add(bill)
    db_session.flush()
    item = AccountsPayableItem(
        ap_id=bill.id,
        line_number=1,
        description='Test Service',
        amount=Decimal('11200.00'),
        vat_category='VATABLE',
        vat_rate=Decimal('12.00'),
        line_total=Decimal('11200.00'),
        vat_amount=Decimal('1200.00'),
        account_id=expense_account.id,
    )
    db_session.add(item)
    db_session.commit()
    return bill


def setup_gl_accounts(db_session):
    expense = get_or_create_account(db_session, '60001', 'Test Expense',
                                    'Expense', 'Debit')
    get_or_create_account(db_session, '20101', 'Accounts Payable - Trade',
                          'Liability', 'Credit')
    get_or_create_account(db_session, '10501', 'Input VAT - Current',
                          'Asset', 'Debit')
    get_or_create_account(db_session, '20301', 'WHT Payable - Expanded',
                          'Liability', 'Credit')
    return expense


class TestDetailPageLayout:

    def test_page_loads_and_shows_voucher_date_label(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_ap_with_line(db_session, vendor, main_branch, expense)
        login(client)
        resp = client.get(f'/accounts-payable/{bill.id}')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Voucher Date' in html
        assert 'Bill Date' not in html

    def test_vendor_invoice_banner_blank(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_ap_with_line(db_session, vendor, main_branch, expense,
                                    vendor_invoice_number='')
        login(client)
        resp = client.get(f'/accounts-payable/{bill.id}')
        html = resp.data.decode('utf-8')
        assert 'Vendor Invoice' in html
        assert '— not provided —' in html

    def test_vendor_invoice_banner_shows_number(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_ap_with_line(db_session, vendor, main_branch, expense,
                                    vendor_invoice_number='INV-2026-001')
        login(client)
        resp = client.get(f'/accounts-payable/{bill.id}')
        html = resp.data.decode('utf-8')
        # The redesigned banner must show "Vendor Invoice" as a standalone section
        # label followed by the invoice number (not buried in vendor info inline).
        # Check that the dedicated banner heading appears in the card body area.
        assert 'Vendor Invoice</span>' in html or 'Vendor Invoice</div>' in html or '>Vendor Invoice<' in html
        assert '— not provided —' not in html

    def test_journal_entry_section_present(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_ap_with_line(db_session, vendor, main_branch, expense)
        login(client)
        resp = client.get(f'/accounts-payable/{bill.id}')
        html = resp.data.decode('utf-8')
        # The redesigned page presents the journal entry under an "Entry" section
        # heading (relabeled from "Journal Entry" in 3cfd8af to match the canonical
        # SI/JE surface jargon). Check for it as a section heading element.
        assert '>Entry</h' in html

    def test_bill_summary_label_present(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_ap_with_line(db_session, vendor, main_branch, expense)
        login(client)
        resp = client.get(f'/accounts-payable/{bill.id}')
        html = resp.data.decode('utf-8')
        assert 'AP Voucher Summary' in html

    def test_line_items_account_title_column_and_no_wht_amt(
            self, client, db_session, admin_user, main_branch):
        expense = setup_gl_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_ap_with_line(db_session, vendor, main_branch, expense)
        login(client)
        resp = client.get(f'/accounts-payable/{bill.id}')
        html = resp.data.decode('utf-8')
        assert 'Account Title' in html
        assert 'WHT Amt' not in html
