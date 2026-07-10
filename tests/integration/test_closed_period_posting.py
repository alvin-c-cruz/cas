"""Integration tests: posting/cancelling into closed accounting periods must be blocked.

Covers:
  FIX 1 — SI post into closed period
  FIX 2 — SI cancel with reversal_date in closed period
  FIX 3 — CRV post into closed period
  FIX 4 — CDV post into closed period
  FIX 5 — JV cancel of an entry dated in a closed period
"""
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.periods.models import AccountingPeriod
from app.sales_invoices.models import SalesInvoice
from app.cash_receipts.models import CashReceiptVoucher
from app.cash_disbursements.models import CashDisbursementVoucher
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration]

CLOSED_YEAR = 2024
CLOSED_MONTH = 1
CLOSED_DATE = date(CLOSED_YEAR, CLOSED_MONTH, 15)


def _login_admin(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def _set_branch(client, branch_id):
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch_id


def _close_period(db_session, year=CLOSED_YEAR, month=CLOSED_MONTH):
    p = AccountingPeriod(year=year, month=month, status='closed')
    db_session.add(p)
    db_session.commit()
    return p


def _make_customer(db_session):
    c = Customer(code='CTEST', name='Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _make_vendor(db_session):
    v = Vendor(code='VTEST', name='Test Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def _make_cash_account(db_session):
    a = Account(code='10101', name='Cash on Hand', account_type='Asset',
                normal_balance='debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


# ── FIX 1: SI post into closed period ────────────────────────────────────────

class TestSIPostClosedPeriod:

    def test_post_blocked_when_invoice_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        """SI with invoice_date in a closed period cannot be posted — stays draft."""
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)

        customer = _make_customer(db_session)
        invoice = SalesInvoice(
            branch_id=main_branch.id,
            invoice_number='SI-CP-0001',
            invoice_date=CLOSED_DATE,
            due_date=CLOSED_DATE,
            customer_id=customer.id,
            customer_name=customer.name,
            notes='',
            status='draft',
            subtotal=Decimal('1000.00'),
            vat_amount=Decimal('0.00'),
            total_before_wt=Decimal('1000.00'),
            withholding_tax_amount=Decimal('0.00'),
            total_amount=Decimal('1000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('1000.00'),
            created_by_id=admin_user.id,
        )
        db_session.add(invoice)
        db_session.commit()

        resp = client.post(f'/sales-invoices/{invoice.id}/post',
                           follow_redirects=False)
        assert resp.status_code == 302  # redirected back

        db_session.refresh(invoice)
        assert invoice.status == 'draft', (
            'Invoice should remain draft when its date is in a closed period')

    def test_post_allowed_when_period_is_open(
            self, client, db_session, admin_user, main_branch):
        """Sanity: SI with an open-period date CAN be posted (period guard passes)."""
        _login_admin(client)
        _set_branch(client, main_branch.id)
        # No closed period created — period is open by default.

        customer = _make_customer(db_session)
        open_date = date(2099, 1, 15)
        invoice = SalesInvoice(
            branch_id=main_branch.id,
            invoice_number='SI-OP-0001',
            invoice_date=open_date,
            due_date=open_date,
            customer_id=customer.id,
            customer_name=customer.name,
            notes='',
            status='draft',
            subtotal=Decimal('500.00'),
            vat_amount=Decimal('0.00'),
            total_before_wt=Decimal('500.00'),
            withholding_tax_amount=Decimal('0.00'),
            total_amount=Decimal('500.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('500.00'),
            created_by_id=admin_user.id,
        )
        db_session.add(invoice)
        db_session.commit()

        resp = client.post(f'/sales-invoices/{invoice.id}/post',
                           follow_redirects=True)
        db_session.refresh(invoice)
        assert invoice.status == 'posted', (
            'Invoice with open-period date should be posted successfully')


# ── FIX 2: SI cancel with reversal_date in closed period ─────────────────────

class TestSICancelClosedPeriod:

    def _make_posted_invoice_with_je(self, db_session, branch_id, customer, user):
        """Create a posted SI with a linked JE (with balanced lines) so the reversal path
        is reachable and would succeed if not for the period guard."""
        # Need an account for JE lines
        acct = Account(code='10301', name='AR Control', account_type='Asset',
                       normal_balance='debit', is_active=True)
        db_session.add(acct)
        db_session.flush()

        je = JournalEntry(
            entry_number='JE-TEST-CANCEL-0001',
            entry_date=date(2099, 3, 1),
            description='Test SI JE',
            entry_type='invoice',
            branch_id=branch_id,
            created_by_id=user.id,
            status='posted',
            is_balanced=True,
            total_debit=Decimal('2000.00'),
            total_credit=Decimal('2000.00'),
        )
        db_session.add(je)
        db_session.flush()

        # Add balanced JE lines so reversal won't fail on "no lines"
        line1 = JournalEntryLine(entry_id=je.id, line_number=1, account_id=acct.id,
                                 description='DR line', debit_amount=Decimal('2000.00'),
                                 credit_amount=Decimal('0.00'))
        line2 = JournalEntryLine(entry_id=je.id, line_number=2, account_id=acct.id,
                                 description='CR line', debit_amount=Decimal('0.00'),
                                 credit_amount=Decimal('2000.00'))
        db_session.add_all([line1, line2])
        db_session.flush()

        invoice = SalesInvoice(
            branch_id=branch_id,
            invoice_number='SI-CANCEL-0001',
            invoice_date=date(2099, 3, 1),
            due_date=date(2099, 3, 31),
            customer_id=customer.id,
            customer_name=customer.name,
            notes='',
            status='posted',
            subtotal=Decimal('2000.00'),
            vat_amount=Decimal('0.00'),
            total_before_wt=Decimal('2000.00'),
            withholding_tax_amount=Decimal('0.00'),
            total_amount=Decimal('2000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('2000.00'),
            created_by_id=user.id,
            journal_entry_id=je.id,
        )
        db_session.add(invoice)
        db_session.commit()
        return invoice

    def test_cancel_blocked_when_reversal_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        """SI cancel with reversal_date in a closed period is rejected — stays posted."""
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)

        customer = _make_customer(db_session)
        invoice = self._make_posted_invoice_with_je(
            db_session, main_branch.id, customer, admin_user)

        resp = client.post(f'/sales-invoices/{invoice.id}/cancel', data={
            'cancel_reason': 'Valid reason that is long enough',
            'reversal_date': CLOSED_DATE.isoformat(),
        }, follow_redirects=False)
        assert resp.status_code == 302

        db_session.refresh(invoice)
        assert invoice.status == 'posted', (
            'Invoice should remain posted when reversal_date is in a closed period')

    def test_cancel_no_reversal_je_when_closed_period(
            self, client, db_session, admin_user, main_branch):
        """No reversal JE is created when cancel is blocked by a closed period."""
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)

        customer = _make_customer(db_session)
        invoice = self._make_posted_invoice_with_je(
            db_session, main_branch.id, customer, admin_user)

        je_count_before = JournalEntry.query.count()
        client.post(f'/sales-invoices/{invoice.id}/cancel', data={
            'cancel_reason': 'Valid reason that is long enough',
            'reversal_date': CLOSED_DATE.isoformat(),
        })
        je_count_after = JournalEntry.query.count()
        assert je_count_after == je_count_before, (
            'No reversal JE should be created when cancel is blocked by closed period')


# ── FIX 3: CRV post into closed period ───────────────────────────────────────

class TestCRVPostClosedPeriod:

    def test_crv_post_blocked_when_crv_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        """Draft CRV with crv_date in a closed period cannot be posted — stays draft."""
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)

        customer = _make_customer(db_session)
        cash = _make_cash_account(db_session)
        crv = CashReceiptVoucher(
            branch_id=main_branch.id,
            crv_number='CR-CP-0001',
            crv_date=CLOSED_DATE,
            customer_id=customer.id,
            customer_name=customer.name,
            payment_method='cash',
            cash_account_id=cash.id,
            notes='',
            status='draft',
            total_ar_applied=Decimal('0.00'),
            total_revenue=Decimal('0.00'),
            total_vat=Decimal('0.00'),
            total_wt=Decimal('0.00'),
            total_amount=Decimal('0.00'),
            created_by_id=admin_user.id,
        )
        db_session.add(crv)
        db_session.commit()

        resp = client.post(f'/cash-receipts/{crv.id}/post',
                           follow_redirects=False)
        assert resp.status_code == 302

        db_session.refresh(crv)
        assert crv.status == 'draft', (
            'CRV should remain draft when its date is in a closed period')


# ── FIX 4: CDV post into closed period ───────────────────────────────────────

class TestCDVPostClosedPeriod:

    def test_cdv_post_blocked_when_cdv_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        """Draft CDV with cdv_date in a closed period cannot be posted — stays draft."""
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)

        vendor = _make_vendor(db_session)
        cash = _make_cash_account(db_session)
        cdv = CashDisbursementVoucher(
            branch_id=main_branch.id,
            cdv_number='CD-CP-0001',
            cdv_date=CLOSED_DATE,
            vendor_id=vendor.id,
            vendor_name=vendor.name,
            payment_method='cash',
            cash_account_id=cash.id,
            notes='',
            status='draft',
            total_ap_applied=Decimal('0.00'),
            total_expense=Decimal('0.00'),
            total_vat=Decimal('0.00'),
            total_wt=Decimal('0.00'),
            total_amount=Decimal('0.00'),
            created_by_id=admin_user.id,
        )
        db_session.add(cdv)
        db_session.commit()

        resp = client.post(f'/cash-disbursements/{cdv.id}/post',
                           follow_redirects=False)
        assert resp.status_code == 302

        db_session.refresh(cdv)
        assert cdv.status == 'draft', (
            'CDV should remain draft when its date is in a closed period')


# ── FIX 5: JV cancel of an entry dated in a closed period ────────────────────

class TestJVCancelClosedPeriod:
    """A posted journal voucher dated inside a closed period must not be cancellable.

    JE `create` guards its date, but `cancel` never did -- so an accountant could
    soft-void a historical posted voucher in a period the books were closed on.
    This matters most for replayed legacy books (`entry_type='legacy_import'`),
    where cancel is the only in-app mutation path: CAS has no journal-entry edit
    route, for drafts or posted entries.
    """

    def _make_posted_je(self, db_session, branch_id, user, entry_date):
        acct = Account(code='10302', name='JV Test Account', account_type='Asset',
                       normal_balance='debit', is_active=True)
        db_session.add(acct)
        db_session.flush()

        je = JournalEntry(
            entry_number='JV-CLOSED-0001',
            entry_date=entry_date,
            description='Posted voucher inside a closed period',
            entry_type='adjustment',
            branch_id=branch_id,
            created_by_id=user.id,
            status='posted',
            is_balanced=True,
            total_debit=Decimal('500.00'),
            total_credit=Decimal('500.00'),
        )
        db_session.add(je)
        db_session.flush()
        db_session.add_all([
            JournalEntryLine(entry_id=je.id, line_number=1, account_id=acct.id,
                             debit_amount=Decimal('500.00'), credit_amount=Decimal('0.00')),
            JournalEntryLine(entry_id=je.id, line_number=2, account_id=acct.id,
                             debit_amount=Decimal('0.00'), credit_amount=Decimal('500.00')),
        ])
        db_session.commit()
        return je

    def test_cancel_blocked_when_entry_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)

        je = self._make_posted_je(db_session, main_branch.id, admin_user, CLOSED_DATE)

        resp = client.post(f'/journal-entries/{je.id}/cancel', follow_redirects=False)
        assert resp.status_code == 302

        db_session.refresh(je)
        assert je.status == 'posted', (
            'A posted JV dated in a closed period must not be cancellable')
        assert je.cancelled_at is None

    def test_cancel_allowed_when_entry_date_in_open_period(
            self, client, db_session, admin_user, main_branch):
        """The guard must not fail closed on an OPEN period -- cancel still works."""
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)   # closes 2024-01 only

        je = self._make_posted_je(db_session, main_branch.id, admin_user,
                                  date(2099, 6, 1))

        client.post(f'/journal-entries/{je.id}/cancel', follow_redirects=False)

        db_session.refresh(je)
        assert je.status == 'cancelled'
        assert je.cancelled_at is not None

    def test_already_cancelled_entry_still_short_circuits(
            self, client, db_session, admin_user, main_branch):
        """The pre-existing 'already cancelled' branch must keep its own message."""
        _login_admin(client)
        _set_branch(client, main_branch.id)

        je = self._make_posted_je(db_session, main_branch.id, admin_user,
                                  date(2099, 6, 1))
        je.status = 'cancelled'
        db_session.commit()

        resp = client.post(f'/journal-entries/{je.id}/cancel', follow_redirects=True)
        assert b'already cancelled' in resp.data.lower()


# ── FIX 6: post into a closed period must be blocked (AP + JV + sales memos) ──
#
# SI/CDV/CRV re-validate the period at post; AP, JV and sales-memos did not. A
# draft created before a period closes could be posted after -- landing posted GL
# into a closed period. Assert at the books level too: the linked draft JE must not
# be promoted either.

class TestAPPostClosedPeriod:

    def _make_draft_ap_with_je(self, db_session, branch_id, vendor, user, ap_date):
        from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
        expense = Account(code='5001', name='Expense', account_type='Expense',
                          normal_balance='debit', is_active=True)
        db_session.add(expense)
        db_session.flush()
        je = JournalEntry(
            entry_number='JE-APCP-0001', entry_date=ap_date, description='AP JE',
            entry_type='purchase', branch_id=branch_id, created_by_id=user.id,
            status='draft', is_balanced=True,
            total_debit=Decimal('1000.00'), total_credit=Decimal('1000.00'))
        db_session.add(je)
        db_session.flush()
        db_session.add_all([
            JournalEntryLine(entry_id=je.id, line_number=1, account_id=expense.id,
                             debit_amount=Decimal('1000.00'), credit_amount=Decimal('0.00')),
            JournalEntryLine(entry_id=je.id, line_number=2, account_id=expense.id,
                             debit_amount=Decimal('0.00'), credit_amount=Decimal('1000.00')),
        ])
        ap = AccountsPayable(
            branch_id=branch_id, ap_number='AP-CP-0001', ap_date=ap_date,
            due_date=ap_date, payee_type='vendor', payee_id=vendor.id,
            vendor_id=vendor.id, vendor_name=vendor.name, status='draft',
            subtotal=Decimal('1000.00'), vat_amount=Decimal('0.00'),
            total_before_wt=Decimal('1000.00'), withholding_tax_amount=Decimal('0.00'),
            total_amount=Decimal('1000.00'), amount_paid=Decimal('0.00'),
            balance=Decimal('1000.00'), journal_entry_id=je.id, created_by_id=user.id)
        db_session.add(ap)
        db_session.flush()
        db_session.add(AccountsPayableItem(
            ap_id=ap.id, line_number=1, description='Service', amount=Decimal('1000.00'),
            line_total=Decimal('1000.00'), vat_amount=Decimal('0.00'),
            account_id=expense.id))
        db_session.commit()
        return ap, je

    def test_ap_post_blocked_when_ap_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        from app.vendors.models import Vendor
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)
        v = Vendor(code='VCP', name='Vendor CP', is_active=True)
        db_session.add(v)
        db_session.commit()
        ap, je = self._make_draft_ap_with_je(db_session, main_branch.id, v, admin_user,
                                             CLOSED_DATE)

        resp = client.post(f'/accounts-payable/{ap.id}/post', follow_redirects=False)
        assert resp.status_code == 302

        db_session.refresh(ap)
        db_session.refresh(je)
        assert ap.status == 'draft'
        assert je.status == 'draft', 'the linked JE must not be promoted either'

    def test_ap_post_allowed_when_period_open(
            self, client, db_session, admin_user, main_branch):
        from app.vendors.models import Vendor
        _login_admin(client)
        _set_branch(client, main_branch.id)
        v = Vendor(code='VOP', name='Vendor OP', is_active=True)
        db_session.add(v)
        db_session.commit()
        ap, je = self._make_draft_ap_with_je(db_session, main_branch.id, v, admin_user,
                                             date(2099, 1, 15))

        client.post(f'/accounts-payable/{ap.id}/post', follow_redirects=True)
        db_session.refresh(ap)
        assert ap.status == 'posted'


class TestJVPostClosedPeriod:

    def _make_draft_je(self, db_session, branch_id, user, entry_date):
        acct = Account(code='10305', name='JV Post Acct', account_type='Asset',
                       normal_balance='debit', is_active=True)
        db_session.add(acct)
        db_session.flush()
        je = JournalEntry(
            entry_number='JV-POST-0001', entry_date=entry_date, description='Draft JV',
            entry_type='adjustment', branch_id=branch_id, created_by_id=user.id,
            status='draft', is_balanced=True,
            total_debit=Decimal('300.00'), total_credit=Decimal('300.00'))
        db_session.add(je)
        db_session.flush()
        db_session.add_all([
            JournalEntryLine(entry_id=je.id, line_number=1, account_id=acct.id,
                             debit_amount=Decimal('300.00'), credit_amount=Decimal('0.00')),
            JournalEntryLine(entry_id=je.id, line_number=2, account_id=acct.id,
                             debit_amount=Decimal('0.00'), credit_amount=Decimal('300.00')),
        ])
        db_session.commit()
        return je

    def test_jv_post_blocked_when_entry_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)
        je = self._make_draft_je(db_session, main_branch.id, admin_user, CLOSED_DATE)

        resp = client.post(f'/journal-entries/{je.id}/post', follow_redirects=False)
        assert resp.status_code == 302
        db_session.refresh(je)
        assert je.status == 'draft'
        assert je.posted_at is None

    def test_jv_post_allowed_when_period_open(
            self, client, db_session, admin_user, main_branch):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        je = self._make_draft_je(db_session, main_branch.id, admin_user, date(2099, 6, 1))

        client.post(f'/journal-entries/{je.id}/post', follow_redirects=True)
        db_session.refresh(je)
        assert je.status == 'posted'


# ── FIX 7/8: cancel with a reversal_date in a closed period (AP / CDV / CRV) ──
#
# SI/AP/CDV/CRV cancel leaves the original JE posted and books a NEW reversing JE
# dated `reversal_date` -- so that date's period must be open. SI validated it; AP,
# CDV and CRV parsed the date and validated nothing, so a reversal could post GL
# into a closed period. The document itself is dated in an OPEN period here (2099),
# so the reversal_date guard is the only thing under test.
#
# JV cancel is deliberately NOT in this set: it posts no reversal JE (it flips the
# entry itself to cancelled, removing GL from the ORIGINAL period), so it validates
# entry_date, not a reversal_date. See TestJVCancelClosedPeriod (FIX 5).

def _posted_doc_je(db_session, branch_id, user, code='10310'):
    acct = Account(code=code, name='Cancel JE Acct', account_type='Asset',
                   normal_balance='debit', is_active=True)
    db_session.add(acct)
    db_session.flush()
    je = JournalEntry(
        entry_number='JE-CX-' + code, entry_date=date(2099, 3, 1),
        description='Doc JE', entry_type='adjustment', branch_id=branch_id,
        created_by_id=user.id, status='posted', is_balanced=True,
        total_debit=Decimal('1000.00'), total_credit=Decimal('1000.00'))
    db_session.add(je)
    db_session.flush()
    db_session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=acct.id,
                         debit_amount=Decimal('1000.00'), credit_amount=Decimal('0.00')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=acct.id,
                         debit_amount=Decimal('0.00'), credit_amount=Decimal('1000.00')),
    ])
    db_session.flush()
    return je


class TestAPCancelClosedPeriod:

    def _posted_ap(self, db_session, branch_id, vendor, user):
        from app.accounts_payable.models import AccountsPayable
        je = _posted_doc_je(db_session, branch_id, user, code='10311')
        ap = AccountsPayable(
            branch_id=branch_id, ap_number='AP-CX-0001', ap_date=date(2099, 3, 1),
            due_date=date(2099, 3, 31), payee_type='vendor', payee_id=vendor.id,
            vendor_id=vendor.id, vendor_name=vendor.name, status='posted',
            subtotal=Decimal('1000.00'), vat_amount=Decimal('0.00'),
            total_before_wt=Decimal('1000.00'), withholding_tax_amount=Decimal('0.00'),
            total_amount=Decimal('1000.00'), amount_paid=Decimal('0.00'),
            balance=Decimal('1000.00'), journal_entry_id=je.id, created_by_id=user.id)
        db_session.add(ap)
        db_session.commit()
        return ap

    def test_cancel_blocked_when_reversal_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        from app.vendors.models import Vendor
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)
        v = Vendor(code='VCX', name='Vendor CX', is_active=True)
        db_session.add(v)
        db_session.commit()
        ap = self._posted_ap(db_session, main_branch.id, v, admin_user)

        before = JournalEntry.query.count()
        resp = client.post(f'/accounts-payable/{ap.id}/cancel', data={
            'cancel_reason': 'Valid reason that is long enough',
            'reversal_date': CLOSED_DATE.isoformat(),
        }, follow_redirects=False)
        assert resp.status_code == 302

        db_session.refresh(ap)
        assert ap.status == 'posted'
        assert JournalEntry.query.count() == before, 'no reversal JE may be created'

    def test_cancel_allowed_when_reversal_date_open(
            self, client, db_session, admin_user, main_branch):
        from app.vendors.models import Vendor
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)
        v = Vendor(code='VCX2', name='Vendor CX2', is_active=True)
        db_session.add(v)
        db_session.commit()
        ap = self._posted_ap(db_session, main_branch.id, v, admin_user)

        client.post(f'/accounts-payable/{ap.id}/cancel', data={
            'cancel_reason': 'Valid reason that is long enough',
            'reversal_date': date(2099, 6, 1).isoformat(),
        }, follow_redirects=True)
        db_session.refresh(ap)
        assert ap.status == 'cancelled'


class TestCDVCancelClosedPeriod:

    def _posted_cdv(self, db_session, branch_id, vendor, cash, user):
        from app.cash_disbursements.models import CashDisbursementVoucher
        je = _posted_doc_je(db_session, branch_id, user, code='10312')
        cdv = CashDisbursementVoucher(
            branch_id=branch_id, cdv_number='CD-CX-0001', cdv_date=date(2099, 3, 1),
            vendor_id=vendor.id, vendor_name=vendor.name, payment_method='cash',
            cash_account_id=cash.id, status='posted',
            total_ap_applied=Decimal('0.00'), total_expense=Decimal('1000.00'),
            total_vat=Decimal('0.00'), total_wt=Decimal('0.00'),
            total_amount=Decimal('1000.00'), journal_entry_id=je.id)
        db_session.add(cdv)
        db_session.commit()
        return cdv

    def test_cancel_blocked_when_reversal_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        from app.vendors.models import Vendor
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)
        v = Vendor(code='VCDX', name='Vendor CDX', is_active=True)
        cash = _make_cash_account(db_session)
        db_session.add(v)
        db_session.commit()
        cdv = self._posted_cdv(db_session, main_branch.id, v, cash, admin_user)

        before = JournalEntry.query.count()
        resp = client.post(f'/cash-disbursements/{cdv.id}/cancel', data={
            'cancel_reason': 'Valid reason that is long enough',
            'reversal_date': CLOSED_DATE.isoformat(),
        }, follow_redirects=False)
        assert resp.status_code == 302

        db_session.refresh(cdv)
        assert cdv.status == 'posted'
        assert JournalEntry.query.count() == before


class TestCRVCancelClosedPeriod:

    def _posted_crv(self, db_session, branch_id, customer, cash, user):
        crv = CashReceiptVoucher(
            branch_id=branch_id, crv_number='CR-CX-0001', crv_date=date(2099, 3, 1),
            customer_id=customer.id, customer_name=customer.name, payment_method='cash',
            cash_account_id=cash.id, status='posted',
            total_ar_applied=Decimal('0.00'), total_revenue=Decimal('1000.00'),
            total_vat=Decimal('0.00'), total_wt=Decimal('0.00'),
            total_amount=Decimal('1000.00'),
            journal_entry_id=_posted_doc_je(db_session, branch_id, user, code='10313').id)
        db_session.add(crv)
        db_session.commit()
        return crv

    def test_cancel_blocked_when_reversal_date_in_closed_period(
            self, client, db_session, admin_user, main_branch):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        _close_period(db_session)
        customer = _make_customer(db_session)
        cash = _make_cash_account(db_session)
        crv = self._posted_crv(db_session, main_branch.id, customer, cash, admin_user)

        before = JournalEntry.query.count()
        resp = client.post(f'/cash-receipts/{crv.id}/cancel', data={
            'cancel_reason': 'Valid reason that is long enough',
            'reversal_date': CLOSED_DATE.isoformat(),
        }, follow_redirects=False)
        assert resp.status_code == 302

        db_session.refresh(crv)
        assert crv.status == 'posted'
        assert JournalEntry.query.count() == before
