"""
Pytest configuration and fixtures for CAS application testing
"""
import pytest
import os
from app import create_app, db
from app.users.models import User
from app.branches.models import Branch
from app.accounts.models import Account
from werkzeug.security import generate_password_hash


@pytest.fixture(scope='session')
def app():
    """Create application for testing session"""
    # Set testing environment variables
    os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only'
    os.environ['TESTING'] = 'True'

    # Create app with testing config
    app = create_app('testing')

    # Establish application context
    with app.app_context():
        yield app


@pytest.fixture(scope='function')
def db_session(app):
    """Create a new database session for each test"""
    with app.app_context():
        # Create all tables
        db.create_all()

        # Yield the session
        yield db.session

        # Cleanup after test
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app, db_session):
    """Test client for making requests"""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI test runner"""
    return app.test_cli_runner()


@pytest.fixture
def auth_headers():
    """Helper for creating authorization headers"""
    def _headers(token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers
    return _headers


# User Fixtures

@pytest.fixture
def admin_user(db_session):
    """Create an admin user"""
    user = User(
        username='admin',
        email='admin@test.com',
        full_name='Admin User',
        role='admin',
        is_active=True
    )
    user.set_password('admin123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def chief_accountant_user(db_session):
    """A Chief Accountant: admin-level accounting reach, all branches, no branch
    assignment and no book_permissions needed (granted by role)."""
    user = User(
        username='chief', email='chief@test.com', full_name='Chief Accountant',
        role='chief_accountant', is_active=True
    )
    user.set_password('chief123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def accountant_user(db_session, main_branch):
    """Create an accountant user assigned to main_branch.

    Accountants are now branch-scoped (like staff/viewer) — they must have at least
    one assigned branch or the before_request gate will redirect them to the picker
    with no options.  Assigning main_branch here keeps every existing test green
    without changes; tests that need an unassigned accountant create one directly.
    """
    user = User(
        username='accountant',
        email='accountant@test.com',
        full_name='Accountant User',
        role='accountant',
        is_active=True
    )
    user.set_password('accountant123')
    from app.users.module_access import default_all_permissions
    user.set_book_permissions(default_all_permissions())
    db_session.add(user)
    db_session.flush()  # get user.id before set_branches
    user.set_branches([main_branch])
    db_session.commit()
    return user


@pytest.fixture
def staff_user(db_session):
    """Create a staff user with all transaction books granted.

    Per-module access (book_permissions) is now enforced for staff, so a default-deny
    staff user would be blocked from the transaction modules. Grant them all here so
    existing tests that exercise AP/SI/CD as staff keep working; tests that specifically
    exercise the gating set their own book_permissions.
    """
    user = User(
        username='staff',
        email='staff@test.com',
        full_name='Staff User',
        role='staff',
        is_active=True
    )
    user.set_password('staff123')
    user.set_book_permissions({
        'accounts_receivable': True,
        'collections': True,
        'accounts_payable': True,
        'payments': True,
        'journal_entries': True,
        # Phase 2 master/ledger modules (deny-by-default in prod; granted here for tests)
        'customers': True,
        'vendors': True,
        'chart_of_accounts': True,
        'ap_aging': True,
        'ar_aging': True,
    })
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def viewer_user(db_session):
    """Create a viewer user"""
    user = User(
        username='viewer',
        email='viewer@test.com',
        full_name='Viewer User',
        role='viewer',
        is_active=True
    )
    user.set_password('viewer123')
    from app.users.module_access import default_all_permissions
    user.set_book_permissions(default_all_permissions())
    db_session.add(user)
    db_session.commit()
    return user


# Branch Fixtures

@pytest.fixture
def main_branch(db_session):
    """Create main branch"""
    branch = Branch(
        code='MAIN',
        name='Main Office',
        address='123 Main St',
        phone='123-456-7890',
        email='main@test.com',
        is_active=True
    )
    db_session.add(branch)
    db_session.commit()
    return branch


@pytest.fixture
def branch_manila(db_session):
    """Create Manila branch"""
    branch = Branch(
        code='MNL',
        name='Manila Branch',
        address='456 Manila St',
        phone='987-654-3210',
        email='manila@test.com',
        is_active=True
    )
    db_session.add(branch)
    db_session.commit()
    return branch


# Account Fixtures

@pytest.fixture
def cash_account(db_session):
    """Create a cash account"""
    account = Account(
        code='1001',
        name='Cash on Hand',
        account_type='Asset',
        classification='Current Asset',
        normal_balance='Debit',
        description='Petty cash and cash on hand'
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture
def revenue_account(db_session):
    """Create a revenue account"""
    account = Account(
        code='4001',
        name='Sales Revenue',
        account_type='Income',
        classification='Operating Revenue',
        normal_balance='Credit',
        description='Revenue from sales'
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture
def expense_account(db_session):
    """Create an expense account"""
    account = Account(
        code='5001',
        name='Office Supplies',
        account_type='Expense',
        classification='Operating Expense',
        normal_balance='Debit',
        description='Office supplies expense'
    )
    db_session.add(account)
    db_session.commit()
    return account


# Authentication Helpers

@pytest.fixture
def authenticated_client(client, admin_user):
    """Client authenticated as admin"""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def login_user():
    """Helper function to login a user in test client"""
    def _login(client, username, password):
        return client.post('/login', data={
            'username': username,
            'password': password
        }, follow_redirects=True)
    return _login


@pytest.fixture
def logout_user():
    """Helper function to logout current user"""
    def _logout(client):
        return client.get('/logout', follow_redirects=True)
    return _logout


# Request Context Helper

@pytest.fixture
def app_context(app):
    """Application context for tests"""
    with app.app_context():
        yield


# Database Helper

@pytest.fixture
def db_with_data(db_session, admin_user, main_branch, cash_account, revenue_account):
    """Database with common test data"""
    return {
        'admin': admin_user,
        'branch': main_branch,
        'cash': cash_account,
        'revenue': revenue_account
    }


# --- R-08 Task 6: vat_lines() fixtures -------------------------------------
# One document with one line each, posted, dated 2026-02-15 (except
# posted_si_on_mar_31). Reuse admin_user/main_branch/cash_account/revenue_account;
# account_id on the line is never read by vat_lines(), so revenue_account is
# reused for all four document types to keep these fixtures small.

@pytest.fixture
def vl_customer(db_session):
    """Minimal Customer to satisfy SI/CRV customer_id FK."""
    from app.customers.models import Customer
    customer = Customer(code='VL-CUST', name='VAT Lines Customer',
                        tin='123-456-789-000')
    db_session.add(customer)
    db_session.commit()
    return customer


@pytest.fixture
def vl_vendor(db_session):
    """Minimal Vendor to satisfy AP/CDV vendor_id FK."""
    from app.vendors.models import Vendor
    vendor = Vendor(code='VL-VEND', name='VAT Lines Vendor',
                    tin='987-654-321-000')
    db_session.add(vendor)
    db_session.commit()
    return vendor


@pytest.fixture
def posted_si_v12(db_session, main_branch, revenue_account, vl_customer):
    """One posted Sales Invoice, one V12/regular line, dated 2026-02-15."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-VL-0001',
        invoice_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='posted',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Consulting services',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def voided_si_v12(db_session, main_branch, revenue_account, vl_customer):
    """One VOIDED Sales Invoice -- must never appear in vat_lines(); real data
    (instance/cas.db) has a voided SI, so this exclusion is not hypothetical."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-VL-VOID-0001',
        invoice_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='voided',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Voided consulting services',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def draft_si_v12(db_session, main_branch, revenue_account, vl_customer):
    """One DRAFT Sales Invoice -- must be excluded from vat_lines()."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-VL-DRAFT-0001',
        invoice_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='draft',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Draft consulting services',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def posted_si_no_category(db_session, main_branch, revenue_account, vl_customer):
    """One posted Sales Invoice whose line has NULL vat_nature (unclassified)."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-VL-NOCAT-0001',
        invoice_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='posted',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Unclassified line',
        amount=Decimal('1000.00'), vat_rate=Decimal('0.00'),
        vat_category=None, vat_nature=None,
        line_total=Decimal('1000.00'), vat_amount=Decimal('0.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def posted_si_zero_rated(db_session, main_branch, revenue_account, vl_customer):
    """One posted Sales Invoice, one V0/zero_export line -- R-08 Task 9:
    proves a zero-rated sale lands in zero_rated_sales, not vatable_sales."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-VL-ZERO-0001',
        invoice_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='posted',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Export sale',
        amount=Decimal('5000.00'), vat_rate=Decimal('0.00'),
        vat_category='V0', vat_nature='zero_export',
        line_total=Decimal('5000.00'), vat_amount=Decimal('0.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def posted_si_exempt(db_session, main_branch, revenue_account, vl_customer):
    """One posted Sales Invoice, one VEX/exempt line -- R-08 Task 9: proves an
    exempt sale lands in vat_exempt_sales."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-VL-EXEMPT-0001',
        invoice_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='posted',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Exempt sale',
        amount=Decimal('3000.00'), vat_rate=Decimal('0.00'),
        vat_category='VEX', vat_nature='exempt',
        line_total=Decimal('3000.00'), vat_amount=Decimal('0.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def posted_si_on_mar_31(db_session, main_branch, revenue_account, vl_customer):
    """One posted Sales Invoice dated the LAST day of the quarter -- proves the
    date range's upper bound is inclusive."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-VL-MAR31-0001',
        invoice_date=date(2026, 3, 31),
        due_date=date(2026, 4, 30),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='posted',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Quarter-end services',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def posted_crv_v12(db_session, main_branch, cash_account, revenue_account, vl_customer):
    """One posted Cash Receipt Voucher, one V12/regular revenue line."""
    from datetime import date
    from decimal import Decimal
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    crv = CashReceiptVoucher(
        branch_id=main_branch.id,
        crv_number='CRV-VL-0001',
        crv_date=date(2026, 2, 15),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        cash_account_id=cash_account.id,
        status='posted',
    )
    line = CRVRevenueLine(
        line_number=1, description='Cash sale',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=revenue_account.id,
    )
    crv.revenue_lines.append(line)
    db_session.add(crv)
    db_session.commit()
    return crv


@pytest.fixture
def posted_ap_v12sv(db_session, main_branch, revenue_account, vl_vendor):
    """One posted Accounts Payable bill, one V12SV/domestic_services line."""
    from datetime import date
    from decimal import Decimal
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    bill = AccountsPayable(
        branch_id=main_branch.id,
        ap_number='AP-VL-0001',
        ap_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        payee_type='vendor', payee_id=vl_vendor.id,
        vendor_id=vl_vendor.id,
        vendor_name=vl_vendor.name,
        vendor_tin=vl_vendor.tin,
        status='posted',
    )
    item = AccountsPayableItem(
        line_number=1, description='Professional services',
        amount=Decimal('5600.00'), vat_rate=Decimal('12.00'),
        vat_category='V12SV', vat_nature='domestic_services',
        line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
        account_id=revenue_account.id,
    )
    bill.line_items.append(item)
    db_session.add(bill)
    db_session.commit()
    return bill


@pytest.fixture
def posted_cdv_v12sv(db_session, main_branch, cash_account, revenue_account, vl_vendor):
    """One posted Cash Disbursement Voucher, one V12SV/domestic_services line."""
    from datetime import date
    from decimal import Decimal
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id,
        cdv_number='CDV-VL-0001',
        cdv_date=date(2026, 2, 15),
        vendor_id=vl_vendor.id,
        vendor_name=vl_vendor.name,
        vendor_tin=vl_vendor.tin,
        cash_account_id=cash_account.id,
        status='posted',
    )
    line = CDVExpenseLine(
        line_number=1, description='Cash-paid services',
        amount=Decimal('5600.00'), vat_rate=Decimal('12.00'),
        vat_category='V12SV', vat_nature='domestic_services',
        line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
        account_id=revenue_account.id,
    )
    cdv.expense_lines.append(line)
    db_session.add(cdv)
    db_session.commit()
    return cdv


@pytest.fixture
def posted_ap_capital_goods(db_session, main_branch, revenue_account, vl_vendor):
    """One posted Accounts Payable bill, one V12CG/capital_goods line -- R-08
    Task 9: proves a capital-goods purchase lands in the capital_goods bucket."""
    from datetime import date
    from decimal import Decimal
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    bill = AccountsPayable(
        branch_id=main_branch.id,
        ap_number='AP-VL-CG-0001',
        ap_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        payee_type='vendor', payee_id=vl_vendor.id,
        vendor_id=vl_vendor.id,
        vendor_name=vl_vendor.name,
        vendor_tin=vl_vendor.tin,
        vendor_invoice_number='INV-CG-0001',
        status='posted',
    )
    item = AccountsPayableItem(
        line_number=1, description='Office equipment',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12CG', vat_nature='capital_goods',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=revenue_account.id,
    )
    bill.line_items.append(item)
    db_session.add(bill)
    db_session.commit()
    return bill


@pytest.fixture
def posted_ap_no_category(db_session, main_branch, revenue_account, vl_vendor):
    """One posted Accounts Payable bill whose line has NULL vat_nature
    (unclassified) -- R-08 Task 9: must not be folded into vatable_purchases."""
    from datetime import date
    from decimal import Decimal
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    bill = AccountsPayable(
        branch_id=main_branch.id,
        ap_number='AP-VL-NOCAT-0001',
        ap_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        payee_type='vendor', payee_id=vl_vendor.id,
        vendor_id=vl_vendor.id,
        vendor_name=vl_vendor.name,
        vendor_tin=vl_vendor.tin,
        vendor_invoice_number='INV-NOCAT-0001',
        status='posted',
    )
    item = AccountsPayableItem(
        line_number=1, description='Unclassified purchase',
        amount=Decimal('1000.00'), vat_rate=Decimal('0.00'),
        vat_category=None, vat_nature=None,
        line_total=Decimal('1000.00'), vat_amount=Decimal('0.00'),
        account_id=revenue_account.id,
    )
    bill.line_items.append(item)
    db_session.add(bill)
    db_session.commit()
    return bill


# --- R-08 Task 7: wht_lines() fixtures -------------------------------------
# Mirrors the Task 6 vat_lines() fixtures above: one document, one line,
# posted, dated 2026-02-15, with wt_id/wt_rate/wt_amount set so the line
# carries withholding. Reuses vl_customer/vl_vendor from Task 6.

@pytest.fixture
def vl_wht_expanded(db_session):
    """Creditable (expanded) WithholdingTax code, 2% -- flows to 2307/QAP/SAWT."""
    from decimal import Decimal
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC160', name='Services', rate=Decimal('2.00'),
                        tax_type='expanded')
    db_session.add(wt)
    db_session.commit()
    return wt


@pytest.fixture
def vl_wht_final(db_session):
    """Non-creditable (final) WithholdingTax code -- must never reach a
    2307/QAP/SAWT surface; tax_type filtering in wht_lines() is what prevents this."""
    from decimal import Decimal
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WF010', name='Final tax on interest',
                        rate=Decimal('20.00'), tax_type='final')
    db_session.add(wt)
    db_session.commit()
    return wt


@pytest.fixture
def posted_ap_with_wht(db_session, main_branch, revenue_account, vl_vendor, vl_wht_expanded):
    """One posted Accounts Payable bill, one line with expanded WHT withheld."""
    from datetime import date
    from decimal import Decimal
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    bill = AccountsPayable(
        branch_id=main_branch.id,
        ap_number='AP-WHT-0001',
        ap_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        payee_type='vendor', payee_id=vl_vendor.id,
        vendor_id=vl_vendor.id,
        vendor_name=vl_vendor.name,
        vendor_tin=vl_vendor.tin,
        status='posted',
    )
    item = AccountsPayableItem(
        line_number=1, description='Professional services',
        amount=Decimal('5600.00'), vat_rate=Decimal('12.00'),
        vat_category='V12SV', vat_nature='domestic_services',
        line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
        wt_id=vl_wht_expanded.id, wt_rate=vl_wht_expanded.rate,
        wt_amount=Decimal('100.00'),
        account_id=revenue_account.id,
    )
    bill.line_items.append(item)
    db_session.add(bill)
    db_session.commit()
    return bill


@pytest.fixture
def posted_ap_with_final_wht(db_session, main_branch, revenue_account, vl_vendor, vl_wht_final):
    """One posted Accounts Payable bill whose line carries FINAL (non-creditable)
    withholding -- must be excluded when wht_lines() is called with
    tax_type='expanded'."""
    from datetime import date
    from decimal import Decimal
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    bill = AccountsPayable(
        branch_id=main_branch.id,
        ap_number='AP-WHT-FINAL-0001',
        ap_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        payee_type='vendor', payee_id=vl_vendor.id,
        vendor_id=vl_vendor.id,
        vendor_name=vl_vendor.name,
        vendor_tin=vl_vendor.tin,
        status='posted',
    )
    item = AccountsPayableItem(
        line_number=1, description='Interest expense',
        amount=Decimal('1000.00'), vat_rate=Decimal('0.00'),
        vat_category=None, vat_nature='exempt',
        line_total=Decimal('1000.00'), vat_amount=Decimal('0.00'),
        wt_id=vl_wht_final.id, wt_rate=vl_wht_final.rate,
        wt_amount=Decimal('200.00'),
        account_id=revenue_account.id,
    )
    bill.line_items.append(item)
    db_session.add(bill)
    db_session.commit()
    return bill


@pytest.fixture
def posted_cdv_with_wht(db_session, main_branch, cash_account, revenue_account, vl_vendor, vl_wht_expanded):
    """One posted Cash Disbursement Voucher, one line with expanded WHT withheld.
    The hole in today's get_alphalist_of_payees(): AP only, misses CDV."""
    from datetime import date
    from decimal import Decimal
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id,
        cdv_number='CDV-WHT-0001',
        cdv_date=date(2026, 2, 15),
        vendor_id=vl_vendor.id,
        vendor_name=vl_vendor.name,
        vendor_tin=vl_vendor.tin,
        cash_account_id=cash_account.id,
        status='posted',
    )
    line = CDVExpenseLine(
        line_number=1, description='Cash-paid services',
        amount=Decimal('5600.00'), vat_rate=Decimal('12.00'),
        vat_category='V12SV', vat_nature='domestic_services',
        line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
        wt_id=vl_wht_expanded.id, wt_rate=vl_wht_expanded.rate,
        wt_amount=Decimal('100.00'),
        account_id=revenue_account.id,
    )
    cdv.expense_lines.append(line)
    db_session.add(cdv)
    db_session.commit()
    return cdv


@pytest.fixture
def cancelled_cdv_with_wht(db_session, main_branch, cash_account, revenue_account, vl_vendor, vl_wht_expanded):
    """One CANCELLED Cash Disbursement Voucher -- must never appear in
    wht_lines(); closes the gap where CRV/CDV voided-exclusion was only
    proven structurally, never by a test."""
    from datetime import date
    from decimal import Decimal
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id,
        cdv_number='CDV-WHT-CANCEL-0001',
        cdv_date=date(2026, 2, 15),
        vendor_id=vl_vendor.id,
        vendor_name=vl_vendor.name,
        vendor_tin=vl_vendor.tin,
        cash_account_id=cash_account.id,
        status='cancelled',
    )
    line = CDVExpenseLine(
        line_number=1, description='Cancelled cash-paid services',
        amount=Decimal('5600.00'), vat_rate=Decimal('12.00'),
        vat_category='V12SV', vat_nature='domestic_services',
        line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
        wt_id=vl_wht_expanded.id, wt_rate=vl_wht_expanded.rate,
        wt_amount=Decimal('100.00'),
        account_id=revenue_account.id,
    )
    cdv.expense_lines.append(line)
    db_session.add(cdv)
    db_session.commit()
    return cdv


@pytest.fixture
def posted_si_with_wht(db_session, main_branch, revenue_account, vl_customer, vl_wht_expanded):
    """One posted Sales Invoice, one line with expanded WHT withheld by the
    customer -- feeds the SAWT reconciliation."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-WHT-0001',
        invoice_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='posted',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Consulting services',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        wt_id=vl_wht_expanded.id, wt_rate=vl_wht_expanded.rate,
        wt_amount=Decimal('200.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def voided_si_with_wht(db_session, main_branch, revenue_account, vl_customer, vl_wht_expanded):
    """One VOIDED Sales Invoice with WHT on its line -- must never appear in
    wht_lines(); closes the gap where voided-exclusion was only proven
    structurally, never by a test (per Task 6's reviewer)."""
    from datetime import date
    from decimal import Decimal
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-WHT-VOID-0001',
        invoice_date=date(2026, 2, 15),
        due_date=date(2026, 3, 17),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='voided',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Voided consulting services',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        wt_id=vl_wht_expanded.id, wt_rate=vl_wht_expanded.rate,
        wt_amount=Decimal('200.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.fixture
def posted_crv_with_wht(db_session, main_branch, cash_account, revenue_account, vl_customer, vl_wht_expanded):
    """One posted Cash Receipt Voucher, one line with expanded WHT withheld by
    the customer -- feeds the SAWT reconciliation."""
    from datetime import date
    from decimal import Decimal
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    crv = CashReceiptVoucher(
        branch_id=main_branch.id,
        crv_number='CRV-WHT-0001',
        crv_date=date(2026, 2, 15),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        cash_account_id=cash_account.id,
        status='posted',
    )
    line = CRVRevenueLine(
        line_number=1, description='Cash sale',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        wt_id=vl_wht_expanded.id, wt_rate=vl_wht_expanded.rate,
        wt_amount=Decimal('200.00'),
        account_id=revenue_account.id,
    )
    crv.revenue_lines.append(line)
    db_session.add(crv)
    db_session.commit()
    return crv
