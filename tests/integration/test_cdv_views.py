"""Integration tests for CDV post, void, and cancel routes."""
import json
import pytest
from decimal import Decimal
from datetime import date

from app.accounts.models import Account
from app.vendors.models import Vendor
from app.withholding_tax.models import WithholdingTax
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
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
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return ap, wt, cash, exp


def make_vendor(db_session):
    v = Vendor(code='CDV01', name='CDV Vendor', check_payee_name='CDV Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def make_posted_bill(db_session, vendor, ap_account, branch_id):
    """Create a posted APV bill with balance = 5000."""
    bill = AccountsPayable(
        branch_id=branch_id,
        ap_number='AP-TEST-CDV-0001',
        ap_date=ph_now().date(),
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


_cdv_counter = 0


def create_draft_cdv(client, vendor, cash_account, ap_lines=None, expense_lines=None,
                     cdv_number=None):
    """Helper: POST a CDV create form.

    ``cdv_number`` defaults to a unique sentinel so the uniqueness guard added in
    B-11 never fires when helpers are called multiple times within the same test.
    """
    global _cdv_counter
    _cdv_counter += 1
    number = cdv_number if cdv_number is not None else f'CD-TEST-{_cdv_counter:04d}'
    today = ph_now().date().isoformat()
    return client.post('/cash-disbursements/create', data={
        'cdv_number': number,
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

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 3000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)

        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
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

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()

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

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 2000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
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
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
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
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
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
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()

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

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
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
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
        client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)
        today = ph_now().date().isoformat()
        client.post(f'/cash-disbursements/{cdv.id}/cancel', data={
            'cancel_reason': 'Duplicate entry — cancelling',
            'reversal_date': today,
        }, follow_redirects=True)

        log = AuditLog.query.filter_by(module='cash_disbursement', action='cancel').first()
        assert log is not None

    def test_cancel_does_not_resurrect_voided_bill(
            self, client, db_session, admin_user, main_branch):
        """If the underlying bill was voided after the CDV paid it,
        cancelling the CDV must NOT change bill status back to posted/partially_paid."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_posted_bill(db_session, vendor, ap, main_branch.id)

        # Create and post a CDV paying the full bill
        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
        client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)

        # Simulate the bill being voided out-of-band
        db_session.refresh(bill)
        bill.status = 'voided'
        db_session.commit()

        # Cancel the CDV — should reverse amount_paid/balance but NOT change status
        today = ph_now().date().isoformat()
        client.post(f'/cash-disbursements/{cdv.id}/cancel', data={
            'cancel_reason': 'Bill was voided — reversing the payment',
            'reversal_date': today,
        }, follow_redirects=True)

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.status == 'cancelled'
        assert bill.status == 'voided', (
            f'Expected bill to stay voided, got {bill.status!r}')
        assert bill.amount_paid == Decimal('0.00'), 'amount_paid must be reversed'
        assert bill.balance == Decimal('5000.00'), 'balance must be restored'


class TestCDVTOCTOU:
    """Re-validation of over-payment at POST time (TOCTOU guard)."""

    def test_second_cdv_post_rejected_when_bill_already_paid(
            self, client, db_session, admin_user, main_branch):
        """Two drafts against the same bill; first post succeeds, second is rejected."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_posted_bill(db_session, vendor, ap, main_branch.id)  # balance=5000

        # Draft CDV 1 — applies full balance
        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 5000.0}]
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv1 = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()

        # Draft CDV 2 — also applies full balance (TOCTOU: passes draft-time check)
        create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        cdv2 = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
        assert cdv2.id != cdv1.id, 'Two distinct CDVs must have been created'

        # Post CDV 1 — succeeds; bill is now paid
        client.post(f'/cash-disbursements/{cdv1.id}/post', follow_redirects=True)
        db_session.refresh(bill)
        assert bill.status == 'paid'
        assert bill.balance == Decimal('0.00')

        # Post CDV 2 — must be rejected (over-payment)
        resp = client.post(f'/cash-disbursements/{cdv2.id}/post', follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(cdv2)
        db_session.refresh(bill)
        assert cdv2.status == 'draft', 'CDV 2 must stay draft after rejection'
        assert bill.balance == Decimal('0.00'), 'Bill balance must not go negative'
        assert bill.amount_paid == Decimal('5000.00'), 'Bill amount_paid must be unchanged'
        assert b'exceeds' in resp.data or b'Cannot post' in resp.data


class TestCDVLineValidation:
    """Server-side validation of client-submitted CDV lines (analyze-page F-001/005/006).

    The AJAX bill loader is branch+vendor scoped, but the POST handler is the real
    trust boundary — a crafted body must be rejected, not persisted.
    """

    def test_rejects_bill_from_another_vendor(self, client, db_session, admin_user, main_branch):
        """F-001: a bill_id belonging to a different vendor cannot be applied."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        other = Vendor(code='CDV02', name='Other Vendor', check_payee_name='Other Vendor', is_active=True)
        db_session.add(other)
        db_session.commit()
        bill = make_posted_bill(db_session, other, ap, main_branch.id)  # belongs to `other`

        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 1000.0}]
        resp = create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)  # CDV is for `vendor`
        assert resp.status_code == 200
        assert b'not available for this vendor' in resp.data
        assert CashDisbursementVoucher.query.count() == 0

    def test_rejects_overpayment(self, client, db_session, admin_user, main_branch):
        """F-005: amount_applied cannot exceed the bill's open balance."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_posted_bill(db_session, vendor, ap, main_branch.id)  # balance 5000
        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 6000.0}]
        resp = create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        assert resp.status_code == 200
        assert b'open balance' in resp.data
        assert CashDisbursementVoucher.query.count() == 0

    def test_rejects_nonpositive_amount(self, client, db_session, admin_user, main_branch):
        """F-005: amount_applied must be positive."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        bill = make_posted_bill(db_session, vendor, ap, main_branch.id)
        ap_lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
                     'original_balance': 5000.0, 'amount_applied': 0}]
        resp = create_draft_cdv(client, vendor, cash, ap_lines=ap_lines)
        assert resp.status_code == 200
        assert CashDisbursementVoucher.query.count() == 0

    def test_rejects_unknown_expense_account(self, client, db_session, admin_user, main_branch):
        """F-006: an expense line must reference a real account."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        expense_lines = [{'description': 'Bogus', 'amount': 1000.0,
                          'vat_category': '', 'account_id': 999999, 'wt_id': None}]
        resp = create_draft_cdv(client, vendor, cash, expense_lines=expense_lines)
        assert resp.status_code == 200
        assert b'postable account' in resp.data
        assert CashDisbursementVoucher.query.count() == 0

    def test_rejects_group_expense_account(self, client, db_session, admin_user, main_branch):
        """F-006: a GROUP (non-leaf) account is not postable."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        # Giving `exp` a child makes it a GROUP (hierarchy is derived from parent_id).
        child = Account(code='60101-01', name='Supplies — Paper', account_type='Expense',
                        normal_balance='debit', is_active=True, parent_id=exp.id)
        db_session.add(child)
        db_session.commit()
        expense_lines = [{'description': 'On a group acct', 'amount': 1000.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        resp = create_draft_cdv(client, vendor, cash, expense_lines=expense_lines)
        assert resp.status_code == 200
        assert b'postable account' in resp.data
        assert CashDisbursementVoucher.query.count() == 0


class TestCDVWHTOverrideDomainError:
    """M2: a domain ValueError raised by _cdv_wht_payable_buckets (via the wt_override
    pre-flight in _post_cdv_je) must surface its own message verbatim in the flash —
    not the generic 'An unexpected error occurred' string — and must not save the CDV.
    """

    def _wht_accounts_and_codes(self, db_session):
        a1 = Account(code='22105-1', name='WHT Payable 1%', account_type='Liability',
                     normal_balance='credit', is_active=True)
        a2 = Account(code='22105-2', name='WHT Payable 2%', account_type='Liability',
                     normal_balance='credit', is_active=True)
        db_session.add_all([a1, a2])
        db_session.commit()
        w1 = WithholdingTax(code='WC158', name='WC158', rate=Decimal('10.00'),
                            is_active=True, payable_account_id=a1.id)
        w2 = WithholdingTax(code='WC160', name='WC160', rate=Decimal('5.00'),
                            is_active=True, payable_account_id=a2.id)
        db_session.add_all([w1, w2])
        db_session.commit()
        return w1, w2

    def test_create_negative_bucket_valueerror_flashed_verbatim(
            self, client, db_session, admin_user, main_branch):
        """wt_override total_wt (2.00) is lower than the summed line WHT (100.00 + 5.00 =
        105.00) by more than the largest bucket -> _cdv_wht_payable_buckets raises
        ValueError('...too far below the computed WHT...'). That message must appear in
        the response verbatim, the generic message must NOT appear, and no CDV is saved.
        """
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        w1, w2 = self._wht_accounts_and_codes(db_session)

        expense_lines = [
            {'description': 'Line 1', 'amount': 1000.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': w1.id},
            {'description': 'Line 2', 'amount': 100.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': w2.id},
        ]
        resp = client.post('/cash-disbursements/create', data={
            'cdv_number': 'CD-TEST-WHTERR-0001',
            'cdv_date': ph_now().date().isoformat(),
            'vendor_id': vendor.id,
            'payment_method': 'cash',
            'cash_account_id': cash.id,
            'notes': 'Test WHT override domain error',
            'ap_lines': json.dumps([]),
            'expense_lines': json.dumps(expense_lines),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '1', 'wt_override_value': '2.00',
        }, follow_redirects=True)

        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'too far below the computed WHT' in body, (
            'domain ValueError message must be flashed verbatim')
        assert 'An unexpected error occurred' not in body, (
            'the generic handler must not swallow this domain error'
        )
        assert CashDisbursementVoucher.query.count() == 0

    def test_edit_negative_bucket_valueerror_flashed_verbatim(
            self, client, db_session, admin_user, main_branch):
        """Same domain ValueError, triggered via the edit() view."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        w1, w2 = self._wht_accounts_and_codes(db_session)

        expense_lines = [{'description': 'Original', 'amount': 500.0,
                          'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
        create_draft_cdv(client, vendor, cash, expense_lines=expense_lines)
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()

        new_expense_lines = [
            {'description': 'Line 1', 'amount': 1000.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': w1.id},
            {'description': 'Line 2', 'amount': 100.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': w2.id},
        ]
        resp = client.post(f'/cash-disbursements/{cdv.id}/edit', data={
            'cdv_number': cdv.cdv_number,
            'cdv_date': ph_now().date().isoformat(),
            'vendor_id': vendor.id,
            'payment_method': 'cash',
            'cash_account_id': cash.id,
            'notes': 'Edited to trigger WHT override domain error',
            'row_version': cdv.row_version,
            'ap_lines': json.dumps([]),
            'expense_lines': json.dumps(new_expense_lines),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '1', 'wt_override_value': '2.00',
        }, follow_redirects=True)

        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'too far below the computed WHT' in body, (
            'domain ValueError message must be flashed verbatim')
        assert 'An unexpected error occurred' not in body, (
            'the generic handler must not swallow this domain error'
        )
        db_session.refresh(cdv)
        assert cdv.status == 'draft'
        assert len(cdv.expense_lines) == 1, 'edit must not have persisted the bad override'
