"""Integration tests for CRV views (create, post, void, cancel, validation)."""
import json
import pytest
from decimal import Decimal
from datetime import date

from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine, CRVRevenueLine
from app.journal_entries.models import JournalEntry
from app.audit.models import AuditLog
from app.utils import ph_now

pytestmark = [pytest.mark.integration]


def login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def setup_accounts(db_session):
    ar   = Account(code='10201', name='AR Trade',          account_type='Asset',    normal_balance='debit',  is_active=True)
    wt   = Account(code='10212', name='WHT Receivable',    account_type='Asset',    normal_balance='debit',  is_active=True)
    cash = Account(code='10101', name='Cash on Hand',      account_type='Asset',    normal_balance='debit',  is_active=True)
    rev  = Account(code='40101', name='Service Revenue',   account_type='Income',   normal_balance='credit', is_active=True)
    db_session.add_all([ar, wt, cash, rev])
    db_session.commit()
    return ar, wt, cash, rev


def make_customer(db_session):
    c = Customer(code='CRV01', name='CRV Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def make_posted_invoice(db_session, customer, ar_account, branch_id):
    """Create a posted SalesInvoice with balance = 5000."""
    inv = SalesInvoice(
        branch_id=branch_id,
        invoice_number='SI-TEST-CRV-0001',
        invoice_date=ph_now().date(),
        due_date=ph_now().date(),
        customer_id=customer.id,
        customer_name=customer.name,
        notes='Test SI',
        status='posted',
        amount_paid=Decimal('0.00'),
        balance=Decimal('5000.00'),
        total_amount=Decimal('5000.00'),
        subtotal=Decimal('5000.00'),
        vat_amount=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


def create_draft_crv(client, customer, cash_account, ar_lines=None, revenue_lines=None):
    today = ph_now().date().isoformat()
    return client.post('/cash-receipts/create', data={
        'crv_number': 'CR-TEST-0001',
        'crv_date': today,
        'customer_id': customer.id,
        'payment_method': 'cash',
        'cash_account_id': cash_account.id,
        'notes': 'Test CRV particulars',
        'ar_lines': json.dumps(ar_lines or []),
        'revenue_lines': json.dumps(revenue_lines or []),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


class TestCRVCreate:

    def test_draft_crv_creates_draft_je(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        inv = make_posted_invoice(db_session, customer, ar, main_branch.id)

        ar_lines = [{'invoice_id': inv.id, 'invoice_number': inv.invoice_number,
                     'original_balance': 5000.0, 'amount_applied': 3000.0}]
        create_draft_crv(client, customer, cash, ar_lines=ar_lines)

        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        assert crv is not None
        assert crv.status == 'draft'
        assert crv.total_ar_applied == Decimal('3000.00')
        assert crv.total_amount == Decimal('3000.00')

        je = db_session.get(JournalEntry, crv.journal_entry_id)
        assert je is not None
        assert je.status == 'draft'
        assert je.entry_type == 'receipt'

    def test_audit_log_on_create(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        revenue_lines = [{'description': 'Service fee', 'amount': 1000.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)

        log = AuditLog.query.filter_by(module='cash_receipt', action='create').first()
        assert log is not None


class TestCRVPost:

    def test_post_promotes_je_and_updates_invoice(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        inv = make_posted_invoice(db_session, customer, ar, main_branch.id)

        ar_lines = [{'invoice_id': inv.id, 'invoice_number': inv.invoice_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_crv(client, customer, cash, ar_lines=ar_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()

        resp = client.post(f'/cash-receipts/{crv.id}/post', follow_redirects=True)
        assert resp.status_code == 200

        db_session.refresh(crv)
        db_session.refresh(inv)
        assert crv.status == 'posted'
        je = db_session.get(JournalEntry, crv.journal_entry_id)
        assert je.status == 'posted'
        assert inv.amount_paid == Decimal('5000.00')
        assert inv.balance == Decimal('0.00')
        assert inv.status == 'paid'

    def test_post_partial_payment_sets_partially_paid(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        inv = make_posted_invoice(db_session, customer, ar, main_branch.id)

        ar_lines = [{'invoice_id': inv.id, 'invoice_number': inv.invoice_number,
                     'original_balance': 5000.0, 'amount_applied': 2000.0}]
        create_draft_crv(client, customer, cash, ar_lines=ar_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        client.post(f'/cash-receipts/{crv.id}/post', follow_redirects=True)

        db_session.refresh(inv)
        assert inv.status == 'partially_paid'
        assert inv.amount_paid == Decimal('2000.00')
        assert inv.balance == Decimal('3000.00')

    def test_post_audit_log(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        revenue_lines = [{'description': 'Consulting', 'amount': 500.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        client.post(f'/cash-receipts/{crv.id}/post', follow_redirects=True)

        log = AuditLog.query.filter_by(module='cash_receipt', action='post').first()
        assert log is not None


class TestCRVVoid:

    def test_void_deletes_draft_je(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        revenue_lines = [{'description': 'Service fee', 'amount': 1000.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        je_id = crv.journal_entry_id

        client.post(f'/cash-receipts/{crv.id}/void',
                    data={'void_reason': 'Entered in error — test void'},
                    follow_redirects=True)

        db_session.refresh(crv)
        assert crv.status == 'voided'
        assert crv.journal_entry_id is None
        assert db_session.get(JournalEntry, je_id) is None

    def test_void_requires_reason(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        revenue_lines = [{'description': 'X', 'amount': 100.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()

        client.post(f'/cash-receipts/{crv.id}/void',
                    data={'void_reason': 'short'},
                    follow_redirects=True)
        db_session.refresh(crv)
        assert crv.status == 'draft'  # not voided


class TestCRVCancel:

    def test_cancel_creates_reversal_and_restores_invoice(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        inv = make_posted_invoice(db_session, customer, ar, main_branch.id)

        ar_lines = [{'invoice_id': inv.id, 'invoice_number': inv.invoice_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_crv(client, customer, cash, ar_lines=ar_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        client.post(f'/cash-receipts/{crv.id}/post', follow_redirects=True)

        today = ph_now().date().isoformat()
        client.post(f'/cash-receipts/{crv.id}/cancel', data={
            'cancel_reason': 'Wrong customer — reversing this receipt now',
            'reversal_date': today,
        }, follow_redirects=True)

        db_session.refresh(crv)
        db_session.refresh(inv)
        assert crv.status == 'cancelled'
        assert inv.status == 'posted'
        assert inv.amount_paid == Decimal('0.00')
        assert inv.balance == Decimal('5000.00')

        reversal = JournalEntry.query.filter_by(
            entry_type='reversal', is_reversing=True
        ).first()
        assert reversal is not None
        assert reversal.status == 'posted'

    def test_cancel_audit_log(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        revenue_lines = [{'description': 'Test revenue', 'amount': 500.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        client.post(f'/cash-receipts/{crv.id}/post', follow_redirects=True)
        today = ph_now().date().isoformat()
        client.post(f'/cash-receipts/{crv.id}/cancel', data={
            'cancel_reason': 'Duplicate entry — cancelling this CRV',
            'reversal_date': today,
        }, follow_redirects=True)

        log = AuditLog.query.filter_by(module='cash_receipt', action='cancel').first()
        assert log is not None


class TestCRVLineValidation:

    def test_rejects_invoice_from_another_customer(self, client, db_session, admin_user, main_branch):
        """invoice_id belonging to a different customer cannot be applied."""
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        other = Customer(code='CRV02', name='Other Customer', is_active=True)
        db_session.add(other)
        db_session.commit()
        inv = make_posted_invoice(db_session, other, ar, main_branch.id)

        ar_lines = [{'invoice_id': inv.id, 'invoice_number': inv.invoice_number,
                     'original_balance': 5000.0, 'amount_applied': 1000.0}]
        resp = create_draft_crv(client, customer, cash, ar_lines=ar_lines)
        assert resp.status_code == 200
        assert b'not available for this customer' in resp.data
        assert CashReceiptVoucher.query.count() == 0

    def test_rejects_overapplication(self, client, db_session, admin_user, main_branch):
        """amount_applied > balance must be rejected."""
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        inv = make_posted_invoice(db_session, customer, ar, main_branch.id)

        ar_lines = [{'invoice_id': inv.id, 'invoice_number': inv.invoice_number,
                     'original_balance': 5000.0, 'amount_applied': 9999.0}]
        resp = create_draft_crv(client, customer, cash, ar_lines=ar_lines)
        assert resp.status_code == 200
        assert b'open balance' in resp.data
        assert CashReceiptVoucher.query.count() == 0

    def test_rejects_nonpositive_amount(self, client, db_session, admin_user, main_branch):
        """amount_applied = 0 must be rejected."""
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        inv = make_posted_invoice(db_session, customer, ar, main_branch.id)

        ar_lines = [{'invoice_id': inv.id, 'invoice_number': inv.invoice_number,
                     'original_balance': 5000.0, 'amount_applied': 0.0}]
        resp = create_draft_crv(client, customer, cash, ar_lines=ar_lines)
        assert resp.status_code == 200
        assert CashReceiptVoucher.query.count() == 0

    def test_rejects_unknown_revenue_account(self, client, db_session, admin_user, main_branch):
        """Revenue line with non-existent account_id must be rejected."""
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)

        revenue_lines = [{'description': 'Bad account', 'amount': 500.0,
                          'vat_category': '', 'account_id': 999999, 'wt_id': None}]
        resp = create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)
        assert resp.status_code == 200
        assert b'postable account' in resp.data
        assert CashReceiptVoucher.query.count() == 0


class TestOpenInvoices:

    def test_open_invoices_returns_only_open(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)

        # Posted (open) invoice
        inv_open = make_posted_invoice(db_session, customer, ar, main_branch.id)

        # Paid invoice — should NOT appear
        inv_paid = SalesInvoice(
            branch_id=main_branch.id,
            invoice_number='SI-TEST-PAID-0001',
            invoice_date=ph_now().date(),
            due_date=ph_now().date(),
            customer_id=customer.id,
            customer_name=customer.name,
            notes='',
            status='paid',
            amount_paid=Decimal('1000.00'),
            balance=Decimal('0.00'),
            total_amount=Decimal('1000.00'),
            subtotal=Decimal('1000.00'),
            vat_amount=Decimal('0.00'),
            withholding_tax_amount=Decimal('0.00'),
        )
        db_session.add(inv_paid)
        db_session.commit()

        resp = client.get(f'/cash-receipts/open-invoices?customer_id={customer.id}')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        ids = [d['id'] for d in data]
        assert inv_open.id in ids
        assert inv_paid.id not in ids

    def test_open_invoices_wrong_branch_returns_empty(self, client, db_session, admin_user, main_branch):
        from app.branches.models import Branch
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)

        # Invoice in a different branch
        other_branch = Branch(name='Other Branch', code='OB', is_active=True)
        db_session.add(other_branch)
        db_session.commit()

        inv = SalesInvoice(
            branch_id=other_branch.id,
            invoice_number='SI-OTHER-BRANCH-0001',
            invoice_date=ph_now().date(),
            due_date=ph_now().date(),
            customer_id=customer.id,
            customer_name=customer.name,
            notes='',
            status='posted',
            amount_paid=Decimal('0.00'),
            balance=Decimal('2000.00'),
            total_amount=Decimal('2000.00'),
            subtotal=Decimal('2000.00'),
            vat_amount=Decimal('0.00'),
            withholding_tax_amount=Decimal('0.00'),
        )
        db_session.add(inv)
        db_session.commit()

        # Session is scoped to main_branch — other branch invoice must not appear
        resp = client.get(f'/cash-receipts/open-invoices?customer_id={customer.id}')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        ids = [d['id'] for d in data]
        assert inv.id not in ids


def login_as(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestCRVRoleGating:
    """A viewer may not create / post / void / cancel CRVs."""

    def test_viewer_blocked_from_create(self, client, db_session, viewer_user, main_branch):
        viewer_user.set_branches([main_branch])
        db_session.commit()
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        login_as(client, 'viewer', 'viewer123')

        # GET the create form — viewer is below staff, must be redirected away.
        resp = client.get('/cash-receipts/create', follow_redirects=False)
        assert resp.status_code in (302, 303)

        # And a POST must not persist a CRV.
        revenue_lines = [{'description': 'Service', 'amount': 500.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)
        assert CashReceiptVoucher.query.count() == 0

    def test_viewer_blocked_from_post(self, client, db_session, admin_user,
                                      viewer_user, main_branch):
        # Admin creates a draft CRV first.
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        revenue_lines = [{'description': 'Service', 'amount': 500.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()

        # Viewer attempts to post — blocked; CRV stays draft.
        viewer_user.set_branches([main_branch])
        db_session.commit()
        client.get('/logout', follow_redirects=True)
        login_as(client, 'viewer', 'viewer123')
        client.post(f'/cash-receipts/{crv.id}/post', follow_redirects=True)
        db_session.refresh(crv)
        assert crv.status == 'draft'


class TestCRVBranchScoping:
    """A CRV in another branch is invisible (404) from the current branch session."""

    def test_cross_branch_detail_returns_404(self, client, db_session, admin_user,
                                             main_branch, branch_manila):
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        revenue_lines = [{'description': 'Service', 'amount': 500.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer, cash, revenue_lines=revenue_lines)
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()

        # In main_branch the CRV is visible.
        resp = client.get(f'/cash-receipts/{crv.id}')
        assert resp.status_code == 200

        # Re-point the session to a different branch — the same CRV must 404.
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = branch_manila.id
        resp = client.get(f'/cash-receipts/{crv.id}')
        assert resp.status_code == 404


class TestCRVTOCTOU:
    """Re-validation of over-application at POST time (TOCTOU guard)."""

    def test_second_crv_post_rejected_when_invoice_already_paid(
            self, client, db_session, admin_user, main_branch):
        """Two drafts against the same invoice; first post succeeds, second is rejected."""
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)
        inv = make_posted_invoice(db_session, customer, ar, main_branch.id)  # balance=5000

        # Draft CRV 1 — applies full balance
        ar_lines = [{'invoice_id': inv.id, 'invoice_number': inv.invoice_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_crv(client, customer, cash, ar_lines=ar_lines)
        crv1 = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()

        # Draft CRV 2 — also applies full balance (TOCTOU: passes draft-time check)
        create_draft_crv(client, customer, cash, ar_lines=ar_lines)
        crv2 = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        assert crv2.id != crv1.id, 'Two distinct CRVs must have been created'

        # Post CRV 1 — succeeds; invoice is now paid
        client.post(f'/cash-receipts/{crv1.id}/post', follow_redirects=True)
        db_session.refresh(inv)
        assert inv.status == 'paid'
        assert inv.balance == Decimal('0.00')

        # Post CRV 2 — must be rejected (over-application)
        resp = client.post(f'/cash-receipts/{crv2.id}/post', follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(crv2)
        db_session.refresh(inv)
        assert crv2.status == 'draft', 'CRV 2 must stay draft after rejection'
        assert inv.balance == Decimal('0.00'), 'Invoice balance must not go negative'
        assert inv.amount_paid == Decimal('5000.00'), 'Invoice amount_paid must be unchanged'
        # Error message must appear in the response
        assert b'exceeds' in resp.data or b'Cannot post' in resp.data


class TestCRVCustomerTin:
    """CRV create/edit must copy customer.tin onto customer_tin (FIX 5)."""

    def test_create_crv_copies_customer_tin(self, client, db_session, admin_user, main_branch):
        """When a customer has a TIN, the saved CRV.customer_tin must equal customer.tin."""
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)

        customer_with_tin = Customer(
            code='CRV-TIN-01', name='TIN Customer', is_active=True, tin='123-456-789-000'
        )
        db_session.add(customer_with_tin)
        db_session.commit()

        revenue_lines = [{'description': 'Service with TIN', 'amount': 1000.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer_with_tin, cash, revenue_lines=revenue_lines)

        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        assert crv is not None, 'CRV was not created'
        assert crv.customer_tin == '123-456-789-000', (
            f'Expected customer_tin=123-456-789-000, got {crv.customer_tin!r}')

    def test_create_crv_null_tin_customer_is_null(
            self, client, db_session, admin_user, main_branch):
        """When a customer has no TIN, customer_tin stays NULL (no error)."""
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)

        customer_no_tin = Customer(
            code='CRV-NOTIN-01', name='No TIN Customer', is_active=True
        )
        db_session.add(customer_no_tin)
        db_session.commit()

        revenue_lines = [{'description': 'Service no tin', 'amount': 500.0,
                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
        create_draft_crv(client, customer_no_tin, cash, revenue_lines=revenue_lines)

        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        assert crv is not None
        assert crv.customer_tin is None
