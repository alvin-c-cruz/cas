"""Unit tests for record status transitions: void, sent, overdue."""
import pytest
from datetime import date, timedelta
from decimal import Decimal
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.accounts.models import Account
from app import db
pytestmark = [pytest.mark.purchase_bills, pytest.mark.unit]



# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def gl_accounts(db_session):
    """Create GL accounts required for void JEs."""
    accounts = {
        'ap': Account(code='20101', name='Accounts Payable - Trade',
                      account_type='Liability', normal_balance='Credit'),
        'ar': Account(code='10201', name='Accounts Receivable - Trade',
                      account_type='Asset', normal_balance='Debit'),
        'input_vat': Account(code='10501', name='Input VAT - Current',
                             account_type='Asset', normal_balance='Debit'),
        'output_vat': Account(code='20201', name='Output VAT - Sales',
                              account_type='Liability', normal_balance='Credit'),
        'expense': Account(code='50230', name='Office Supplies Expense',
                           account_type='Expense', normal_balance='Debit'),
        'revenue': Account(code='40101', name='Sales Revenue',
                           account_type='Revenue', normal_balance='Credit'),
    }
    for a in accounts.values():
        db_session.add(a)
    db_session.commit()
    # _post_bill_je buckets input VAT by category account (B-014), so the
    # VATABLE category used by the bill fixtures must be mapped.
    from app.vat_categories.models import VATCategory
    db_session.add(VATCategory(code='VATABLE', name='VATable Purchases',
                               rate=Decimal('12.00'), is_active=True,
                               input_vat_account_id=accounts['input_vat'].id))
    db_session.commit()
    return accounts


@pytest.fixture
def test_vendor(db_session):
    """Create a minimal vendor for FK compliance."""
    from app.vendors.models import Vendor
    vendor = Vendor(code='V001', name='Test Vendor', is_active=True)
    db_session.add(vendor)
    db_session.commit()
    return vendor


@pytest.fixture
def test_customer(db_session):
    """Create a minimal customer for FK compliance."""
    from app.customers.models import Customer
    customer = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(customer)
    db_session.commit()
    return customer


@pytest.fixture
def posted_bill(db_session, admin_user, main_branch, gl_accounts, test_vendor):
    """Create a posted purchase bill with one line item and no WT."""
    bill = PurchaseBill(
        bill_number='PB-TEST-0001',
        bill_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        vendor_id=test_vendor.id,
        vendor_name='Test Vendor',
        payment_terms='Net 30',
        subtotal=Decimal('1000.00'),
        vat_amount=Decimal('120.00'),
        total_before_wt=Decimal('1120.00'),
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('1120.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('1120.00'),
        status='posted',
        branch_id=main_branch.id,
        created_by_id=admin_user.id,
        notes='Unit test bill — office supplies purchase'
    )
    db_session.add(bill)
    db_session.flush()

    item = PurchaseBillItem(
        bill_id=bill.id, line_number=1,
        description='Office Supplies', amount=Decimal('1120.00'),
        vat_category='VATABLE', vat_rate=Decimal('12.00'),
        line_total=Decimal('1120.00'), vat_amount=Decimal('120.00'),
        account_id=gl_accounts['expense'].id
    )
    db_session.add(item)
    db_session.flush()

    # Posted bills always carry a stored JE (created on save, promoted on
    # post); the reversal helper mirrors it, so the fixture must book one.
    from app.purchase_bills.views import _post_bill_je
    je = _post_bill_je(bill, admin_user.id)
    bill.journal_entry_id = je.id
    db_session.commit()
    return bill


@pytest.fixture
def posted_invoice(db_session, admin_user, main_branch, gl_accounts, test_customer):
    """Create a posted sales invoice with one line item."""
    invoice = SalesInvoice(
        invoice_number='SI-TEST-0001',
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        customer_id=test_customer.id,
        customer_name='Test Customer',
        payment_terms='Net 30',
        subtotal=Decimal('2000.00'),
        vat_amount=Decimal('240.00'),
        total_amount=Decimal('2240.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('2240.00'),
        status='posted',
        branch_id=main_branch.id,
        created_by_id=admin_user.id
    )
    db_session.add(invoice)
    db_session.flush()

    item = SalesInvoiceItem(
        invoice_id=invoice.id, line_number=1,
        description='Consulting Services', amount=Decimal('2240.00'),
        vat_category='VATABLE',
        vat_rate=Decimal('12.00'), line_total=Decimal('2000.00'),
        vat_amount=Decimal('240.00'), account_id=gl_accounts['revenue'].id
    )
    db_session.add(item)
    db_session.commit()
    return invoice


# ── Model field tests ────────────────────────────────────────────────────────

def test_purchase_bill_has_void_fields(db_session, posted_bill):
    assert hasattr(posted_bill, 'voided_at')
    assert hasattr(posted_bill, 'voided_by_id')
    assert hasattr(posted_bill, 'void_reason')
    assert posted_bill.voided_at is None
    assert posted_bill.voided_by_id is None
    assert posted_bill.void_reason is None


def test_sales_invoice_has_sent_and_void_fields(db_session, posted_invoice):
    assert hasattr(posted_invoice, 'sent_at')
    assert hasattr(posted_invoice, 'sent_by_id')
    assert hasattr(posted_invoice, 'voided_at')
    assert hasattr(posted_invoice, 'voided_by_id')
    assert hasattr(posted_invoice, 'void_reason')
    assert posted_invoice.sent_at is None
    assert posted_invoice.voided_at is None


# ── Bill cancel/reversal JE tests ────────────────────────────────────────────

def test_create_bill_void_je_balanced(app, db_session, posted_bill, admin_user, gl_accounts):
    """Reversal JE must have total_debit == total_credit."""
    from app.purchase_bills.views import _create_reversal_je as _create_bill_void_je
    je = _create_bill_void_je(posted_bill, date.today(), admin_user.id, label='Cancel')
    db_session.flush()
    assert je.is_balanced, f"JE not balanced: DR={je.total_debit} CR={je.total_credit}"
    assert je.total_debit == Decimal('1120.00')
    assert je.total_credit == Decimal('1120.00')


def test_create_bill_void_je_reference_format(app, db_session, posted_bill, admin_user, gl_accounts):
    from app.purchase_bills.views import _create_reversal_je as _create_bill_void_je
    je = _create_bill_void_je(posted_bill, date.today(), admin_user.id, label='Cancel')
    assert je.reference == 'CANCEL-PB-TEST-0001'
    assert je.entry_type == 'reversal'
    assert je.status == 'posted'
    assert je.branch_id == posted_bill.branch_id


def test_create_bill_void_je_without_stored_je_raises(app, db_session, posted_bill, admin_user, gl_accounts):
    """The reversal mirrors the stored JE, so a missing JE must fail clearly
    rather than rebuild a (possibly wrong) reversal from bill totals."""
    from app.purchase_bills.views import _create_reversal_je as _create_bill_void_je
    posted_bill.journal_entry_id = None
    db_session.commit()
    with pytest.raises(ValueError, match='no stored journal entry'):
        _create_bill_void_je(posted_bill, date.today(), admin_user.id, label='Cancel')


def test_create_bill_void_je_mirrors_stored_lines(app, db_session, posted_bill, admin_user, gl_accounts):
    """Each reversal line swaps the debit/credit of the stored JE line."""
    from app.purchase_bills.views import _create_reversal_je as _create_bill_void_je
    je = _create_bill_void_je(posted_bill, date.today(), admin_user.id, label='Cancel')
    db_session.flush()
    source = posted_bill.journal_entry
    src_lines = {l.account_id: l for l in source.lines.all()}
    rev_lines = {l.account_id: l for l in je.lines.all()}
    assert set(rev_lines) == set(src_lines)
    for account_id, src in src_lines.items():
        rev = rev_lines[account_id]
        assert rev.debit_amount == src.credit_amount
        assert rev.credit_amount == src.debit_amount


def test_bill_void_sets_status_and_fields(app, db_session, posted_bill, admin_user, gl_accounts):
    """After voiding, bill fields are updated correctly."""
    from app.purchase_bills.views import _create_reversal_je as _create_bill_void_je
    from app.utils import ph_now
    _create_bill_void_je(posted_bill, date.today(), admin_user.id, label='Cancel')
    posted_bill.status = 'voided'
    posted_bill.voided_by_id = admin_user.id
    posted_bill.voided_at = ph_now()
    posted_bill.void_reason = 'Wrong vendor entered in error'
    db_session.commit()

    db_session.refresh(posted_bill)
    assert posted_bill.status == 'voided'
    assert posted_bill.void_reason == 'Wrong vendor entered in error'
    assert posted_bill.voided_by_id == admin_user.id
    assert posted_bill.voided_at is not None


def test_bill_void_creates_audit_entry(app, db_session, client, posted_bill, admin_user, gl_accounts):
    """Void route creates an audit log entry."""
    from app.purchase_bills.views import _create_reversal_je as _create_bill_void_je
    from app.audit.utils import log_audit
    from app.audit.models import AuditLog

    _create_bill_void_je(posted_bill, date.today(), admin_user.id, label='Cancel')
    posted_bill.status = 'voided'
    posted_bill.voided_by_id = admin_user.id
    void_reason = 'Duplicate entry created in error'
    posted_bill.void_reason = void_reason
    db_session.commit()

    log_audit(
        module='purchase_bill',
        action='void',
        record_id=posted_bill.id,
        record_identifier=f'{posted_bill.bill_number} - {posted_bill.vendor_name}',
        notes=f'Voided by {admin_user.username}. Reason: {void_reason}'
    )

    entry = AuditLog.query.filter_by(
        module='purchase_bill', action='void', record_id=posted_bill.id
    ).first()
    assert entry is not None
    assert admin_user.username in entry.notes
    assert void_reason in entry.notes


# ── Invoice void JE tests ────────────────────────────────────────────────────

def test_create_invoice_void_je_balanced(app, db_session, posted_invoice, admin_user, gl_accounts):
    from app.sales_invoices.views import _create_invoice_void_je
    je = _create_invoice_void_je(posted_invoice, date.today(), admin_user.id)
    db_session.flush()
    assert je.is_balanced, f"JE not balanced: DR={je.total_debit} CR={je.total_credit}"
    assert je.total_debit == Decimal('2240.00')
    assert je.total_credit == Decimal('2240.00')


def test_create_invoice_void_je_reference_format(app, db_session, posted_invoice, admin_user, gl_accounts):
    from app.sales_invoices.views import _create_invoice_void_je
    je = _create_invoice_void_je(posted_invoice, date.today(), admin_user.id)
    assert je.reference == 'VOID-SI-TEST-0001'
    assert je.entry_type == 'reversal'
    assert je.branch_id == posted_invoice.branch_id


def test_create_invoice_void_je_missing_ar_raises(app, db_session, posted_invoice, admin_user, gl_accounts):
    """Void must fail clearly if AR account is missing."""
    from app.sales_invoices.views import _create_invoice_void_je
    # Remove the AR account so the helper can't find it
    db_session.delete(gl_accounts['ar'])
    db_session.commit()
    with pytest.raises(ValueError, match='10201'):
        _create_invoice_void_je(posted_invoice, date.today(), admin_user.id)


# ── Send status tests ────────────────────────────────────────────────────────

def test_sales_invoice_can_be_marked_sent(db_session, admin_user, main_branch, test_customer):
    from app.utils import ph_now
    invoice = SalesInvoice(
        invoice_number='SI-TEST-0002', invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        customer_id=test_customer.id, customer_name='Test Customer',
        payment_terms='Net 30', subtotal=Decimal('500.00'),
        vat_amount=Decimal('0.00'), total_amount=Decimal('500.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('500.00'),
        status='draft', branch_id=main_branch.id, created_by_id=admin_user.id
    )
    db_session.add(invoice)
    db_session.commit()

    invoice.status = 'sent'
    invoice.sent_at = ph_now()
    invoice.sent_by_id = admin_user.id
    db_session.commit()

    db_session.refresh(invoice)
    assert invoice.status == 'sent'
    assert invoice.sent_at is not None
    assert invoice.sent_by_id == admin_user.id


def test_sent_invoice_can_be_posted(db_session, admin_user, main_branch, test_customer):
    """A sent invoice can transition to posted (not just draft)."""
    from app.utils import ph_now

    invoice = SalesInvoice(
        invoice_number='SI-TEST-0003', invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        customer_id=test_customer.id, customer_name='Test Customer',
        payment_terms='Net 30', subtotal=Decimal('500.00'),
        vat_amount=Decimal('0.00'), total_amount=Decimal('500.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('500.00'),
        status='sent', branch_id=main_branch.id, created_by_id=admin_user.id
    )
    db_session.add(invoice)
    db_session.commit()

    invoice.status = 'posted'
    invoice.posted_by_id = admin_user.id
    invoice.posted_at = ph_now()
    db_session.commit()

    db_session.refresh(invoice)
    assert invoice.status == 'posted'
