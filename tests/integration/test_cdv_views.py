"""Integration tests for CDV post, void, and cancel routes."""
import json
import pytest
from decimal import Decimal
from datetime import date

from app.accounts.models import Account
from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine, CDVExpenseLine
from app.journal_entries.models import JournalEntry
from app.audit.models import AuditLog
from app.utils import ph_now

pytestmark = [pytest.mark.integration]


def login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def setup_accounts(db_session):
    ap  = Account(code='20101', name='AP Trade',  account_type='Liability', normal_balance='credit', is_active=True)
    wt  = Account(code='20301', name='WHT Payable', account_type='Liability', normal_balance='credit', is_active=True)
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset', normal_balance='debit', is_active=True)
    exp  = Account(code='60101', name='Office Supplies', account_type='Expense', normal_balance='debit', is_active=True)
    db_session.add_all([ap, wt, cash, exp])
    db_session.commit()
    return ap, wt, cash, exp


def make_vendor(db_session):
    v = Vendor(code='CDV01', name='CDV Vendor', check_payee_name='CDV Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def make_posted_bill(db_session, vendor, ap_account, branch_id):
    """Create a posted APV bill with balance = 5000."""
    bill = PurchaseBill(
        branch_id=branch_id,
        bill_number='AP-TEST-CDV-0001',
        bill_date=ph_now().date(),
        due_date=ph_now().date(),
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        notes='Test AP bill',
        status='posted',
        amount_paid=Decimal('0.00'),
        balance=Decimal('5000.00'),
        total_amount=Decimal('5000.00'),
        subtotal=Decimal('5000.00'),
        vat_amount=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(bill)
    db_session.commit()
    return bill


def create_draft_cdv(client, vendor, cash_account, ap_lines=None, expense_lines=None):
    today = ph_now().date().isoformat()
    return client.post('/cash-disbursements/create', data={
        'cdv_number': 'CD-TEST-0001',
        'cdv_date': today,
        'vendor_id': vendor.id,
        'payment_method': 'cash',
        'cash_account_id': cash_account.id,
        'notes': 'Test CDV particulars',
        'ap_lines': json.dumps(ap_lines or []),
        'expense_lines': json.dumps(expense_lines or []),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


class TestCDVCreate:
    def test_draft_cdv_creates_draft_je(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_posted_bill(db_session, vendor, ap, main_branch.id)

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.bill_number,
                     'original_balance': 5000.0, 'amount_applied': 3000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)

        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-TEST-0001').first()
        assert cdv is not None
        assert cdv.status == 'draft'
        assert cdv.total_ap_applied == Decimal('3000.00')
        assert cdv.total_amount == Decimal('3000.00')

        je = db_session.get(JournalEntry, cdv.journal_entry_id)
        assert je is not None
        assert je.status == 'draft'
        assert je.entry_type == 'disbursement'

    def test_audit_log_on_create(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        expense_lines = [{'description': 'Office supplies', 'amount': 1000.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        create_draft_cdv(client, vendor, cash, expense_lines=expense_lines)

        log = AuditLog.query.filter_by(module='cash_disbursement', action='create').first()
        assert log is not None


class TestCDVPost:
    def test_post_promotes_je_and_updates_bill(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_posted_bill(db_session, vendor, ap, main_branch.id)

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.bill_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-TEST-0001').first()

        resp = client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)
        assert resp.status_code == 200

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.status == 'posted'
        je = db_session.get(JournalEntry, cdv.journal_entry_id)
        assert je.status == 'posted'
        assert bill.amount_paid == Decimal('5000.00')
        assert bill.balance == Decimal('0.00')
        assert bill.status == 'paid'

    def test_post_partial_payment_sets_partially_paid(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_posted_bill(db_session, vendor, ap, main_branch.id)

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.bill_number,
                     'original_balance': 5000.0, 'amount_applied': 2000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-TEST-0001').first()
        client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)

        db_session.refresh(bill)
        assert bill.status == 'partially_paid'
        assert bill.amount_paid == Decimal('2000.00')
        assert bill.balance == Decimal('3000.00')

    def test_post_audit_log(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        expense_lines = [{'description': 'Supplies', 'amount': 500.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        create_draft_cdv(client, vendor, cash, expense_lines=expense_lines)
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-TEST-0001').first()
        client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)

        log = AuditLog.query.filter_by(module='cash_disbursement', action='post').first()
        assert log is not None


class TestCDVVoid:
    def test_void_deletes_draft_je(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        expense_lines = [{'description': 'Supplies', 'amount': 1000.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        create_draft_cdv(client, vendor, cash, expense_lines=expense_lines)
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-TEST-0001').first()
        je_id = cdv.journal_entry_id

        client.post(f'/cash-disbursements/{cdv.id}/void',
                    data={'void_reason': 'Entered in error — test'},
                    follow_redirects=True)

        db_session.refresh(cdv)
        assert cdv.status == 'voided'
        assert cdv.journal_entry_id is None
        assert db_session.get(JournalEntry, je_id) is None

    def test_void_requires_reason(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        expense_lines = [{'description': 'X', 'amount': 100.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        create_draft_cdv(client, vendor, cash, expense_lines=expense_lines)
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-TEST-0001').first()

        client.post(f'/cash-disbursements/{cdv.id}/void',
                    data={'void_reason': 'short'},
                    follow_redirects=True)
        db_session.refresh(cdv)
        assert cdv.status == 'draft'  # not voided


class TestCDVCancel:
    def test_cancel_creates_reversal_and_restores_bill(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_posted_bill(db_session, vendor, ap, main_branch.id)

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.bill_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-TEST-0001').first()
        client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)

        today = ph_now().date().isoformat()
        client.post(f'/cash-disbursements/{cdv.id}/cancel', data={
            'cancel_reason': 'Paid the wrong vendor — reversing now',
            'reversal_date': today,
        }, follow_redirects=True)

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.status == 'cancelled'
        assert bill.status == 'posted'
        assert bill.amount_paid == Decimal('0.00')
        assert bill.balance == Decimal('5000.00')

        # Reversal JE must exist
        reversal = JournalEntry.query.filter_by(
            entry_type='reversal', is_reversing=True
        ).first()
        assert reversal is not None
        assert reversal.status == 'posted'

    def test_cancel_audit_log(self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        expense_lines = [{'description': 'Test', 'amount': 500.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        create_draft_cdv(client, vendor, cash, expense_lines=expense_lines)
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-TEST-0001').first()
        client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)
        today = ph_now().date().isoformat()
        client.post(f'/cash-disbursements/{cdv.id}/cancel', data={
            'cancel_reason': 'Duplicate entry — cancelling',
            'reversal_date': today,
        }, follow_redirects=True)

        log = AuditLog.query.filter_by(module='cash_disbursement', action='cancel').first()
        assert log is not None
