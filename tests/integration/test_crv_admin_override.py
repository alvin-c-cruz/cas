"""The administrator may edit or delete a cash receipt voucher after it is posted.

Owner, 2026-10-07: "build SI next ... and then CRV". Same terms as every document in
app-docs/admin-override-checklist.md -- admin only, a reason of 10+ characters in the audit
log, closed periods and bank-reconciled lines still refuse, edit in place (same JE number
and posting stamp), delete is a hard delete with a snapshot.

Specific to the CRV: what it collected sits on the invoices (and debit notes) it applied
to. An edit takes those collections off, validates the edited lines against the restored
balances, and puts them back; a delete takes them off for good, so the invoices reopen.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.audit.models import AuditLog
from app.cash_receipts.models import CashReceiptVoucher
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.sales_invoices.models import SalesInvoice
from tests.integration.test_si_admin_override import (TODAY, _accounts, _close_period,
                                                      _customer, _login, _pay, _posted_si)

pytestmark = [pytest.mark.integration]

REASON = 'Collection encoded against the wrong amount'


# ------------------------------------------------------------------ helpers

def _posted_crv(client, db_session, admin_user, main_branch, applied=2000):
    """A 5,000 invoice and a posted receipt collecting *applied* of it."""
    si, cust, ar, rev, cash = _posted_si(client, db_session, admin_user, main_branch)
    crv = _pay(client, si, cust, cash, applied)
    crv = db.session.get(CashReceiptVoucher, crv.id)
    assert crv.status == 'posted'
    return crv, si, cust, cash


def _edit(client, crv, cust, cash, si, amount, reason=REASON, original_balance=None):
    data = {
        'crv_number': crv.crv_number, 'crv_date': crv.crv_date.isoformat(),
        'customer_id': cust.id, 'payment_method': 'cash', 'cash_account_id': cash.id,
        'notes': crv.notes, 'row_version': crv.row_version,
        'ar_lines': json.dumps([{'invoice_id': si.id, 'invoice_number': si.invoice_number,
                                 'original_balance': original_balance or 5000.0,
                                 'amount_applied': amount}]),
        'revenue_lines': json.dumps([]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }
    if reason is not None:
        data['admin_reason'] = reason
    return client.post(f'/cash-receipts/{crv.id}/edit', data=data, follow_redirects=True)


def _delete(client, crv_id, reason=REASON):
    data = {} if reason is None else {'delete_reason': reason}
    return client.post(f'/cash-receipts/{crv_id}/delete', data=data, follow_redirects=True)


def _si(si_id):
    db.session.expire_all()
    return db.session.get(SalesInvoice, si_id)


def _audit(action, record_id):
    return (AuditLog.query.filter_by(module='cash_receipt', action=action, record_id=record_id)
            .order_by(AuditLog.id.desc()).first())


def _reconcile(db_session, crv, cash, main_branch):
    """Clear the receipt's cash line in a bank reconciliation."""
    from app.bank_accounts.models import BankAccount
    from app.bank_reconciliation.models import BankReconciliation, ReconciliationItem
    bank = BankAccount(branch_id=main_branch.id, code='CBC919', name='CBC 919', account_id=cash.id)
    db_session.add(bank)
    db_session.flush()
    rec = BankReconciliation(bank_account_id=bank.id, statement_date=TODAY,
                             statement_ending_balance=Decimal('0'), beginning_balance=Decimal('0'))
    db_session.add(rec)
    db_session.flush()
    line = JournalEntryLine.query.filter_by(entry_id=crv.journal_entry_id,
                                            account_id=cash.id).first()
    db_session.add(ReconciliationItem(reconciliation_id=rec.id, je_line_id=line.id))
    db_session.commit()


# ------------------------------------------------------------------ edit

class TestAdminEditsAPostedReceipt:

    def test_a_changed_amount_is_reapplied_to_the_invoice(self, client, db_session, admin_user,
                                                          main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        je_number, posted_at = crv.journal_entry.entry_number, crv.journal_entry.posted_at
        _edit(client, crv, cust, cash, si, 1500)
        inv = _si(si.id)
        assert inv.amount_paid == Decimal('1500.00') and inv.balance == Decimal('3500.00')
        assert inv.status == 'partially_paid'
        crv = db.session.get(CashReceiptVoucher, crv.id)
        assert crv.status == 'posted' and crv.total_amount == Decimal('1500.00')
        je = crv.journal_entry
        assert je.entry_number == je_number and je.posted_at == posted_at
        assert je.status == 'posted' and je.total_debit == Decimal('1500.00')
        assert JournalEntry.query.filter_by(entry_type=je.entry_type).count() == 1

    def test_collecting_the_whole_balance_marks_the_invoice_paid(
            self, client, db_session, admin_user, main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        _edit(client, crv, cust, cash, si, 5000)
        inv = _si(si.id)
        assert inv.status == 'paid' and inv.balance == Decimal('0.00')

    def test_more_than_the_invoice_is_refused(self, client, db_session, admin_user, main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        body = _edit(client, crv, cust, cash, si, 5500).data.decode()
        assert 'open balance' in body
        inv = _si(si.id)
        assert inv.amount_paid == Decimal('2000.00')     # the original collection still stands
        assert db.session.get(CashReceiptVoucher, crv.id).total_amount == Decimal('2000.00')

    def test_the_edit_is_audited_with_its_reason(self, client, db_session, admin_user,
                                                 main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        _edit(client, crv, cust, cash, si, 1500)
        row = _audit('admin_edit_posted', crv.id)
        assert row is not None and REASON in row.notes

    def test_a_reason_is_required(self, client, db_session, admin_user, main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        body = _edit(client, crv, cust, cash, si, 1500, reason='short').data.decode()
        assert 'reason of at least 10 characters' in body
        assert _si(si.id).amount_paid == Decimal('2000.00')

    def test_an_accountant_still_cannot_edit_a_posted_receipt(
            self, client, db_session, admin_user, accountant_user, main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        _login(client, accountant_user, main_branch)
        _edit(client, crv, cust, cash, si, 1500)
        assert _si(si.id).amount_paid == Decimal('2000.00')

    def test_a_closed_period_refuses(self, client, db_session, admin_user, main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        _close_period(db_session, crv.crv_date)
        body = _edit(client, crv, cust, cash, si, 1500).data.decode()
        assert 'Cannot edit posted CRV' in body
        assert _si(si.id).amount_paid == Decimal('2000.00')

    def test_a_bank_reconciled_receipt_refuses(self, client, db_session, admin_user,
                                               main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        _reconcile(db_session, crv, cash, main_branch)
        body = _edit(client, crv, cust, cash, si, 1500).data.decode()
        assert 'reconcil' in body.lower()
        assert _si(si.id).amount_paid == Decimal('2000.00')

    def test_the_edit_form_asks_for_the_reason(self, client, db_session, admin_user,
                                               main_branch):
        crv, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        body = client.get(f'/cash-receipts/{crv.id}/edit').data.decode()
        assert 'Edit Posted CRV (admin)' in body and 'name="admin_reason"' in body


# ------------------------------------------------------------------ delete

class TestAdminDeletesAReceipt:

    def test_the_invoice_reopens(self, client, db_session, admin_user, main_branch):
        crv, si, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        crv_id, je_id = crv.id, crv.journal_entry_id
        _delete(client, crv_id)
        inv = _si(si.id)
        assert inv.amount_paid == Decimal('0.00') and inv.balance == Decimal('5000.00')
        assert inv.status == 'posted'
        assert db.session.get(CashReceiptVoucher, crv_id) is None
        assert db.session.get(JournalEntry, je_id) is None

    def test_the_number_is_free_again(self, client, db_session, admin_user, main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        _delete(client, crv.id)
        _pay(client, _si(si.id), cust, cash, 100, number='CR-AO-1', post=False)
        reused = CashReceiptVoucher.query.filter_by(crv_number='CR-AO-1').all()
        assert [c.total_amount for c in reused] == [Decimal('100.00')]

    def test_the_delete_is_audited_with_a_snapshot(self, client, db_session, admin_user,
                                                   main_branch):
        crv, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        crv_id = crv.id
        _delete(client, crv_id)
        row = _audit('admin_delete', crv_id)
        assert row is not None and REASON in row.notes
        snap = row.old_values if isinstance(row.old_values, dict) else json.loads(row.old_values)
        assert snap['crv_number'] == 'CR-AO-1' and snap['total_amount'] == '2000.00'
        assert snap['ar_lines'][0]['amount_applied'] == '2000.00'
        assert snap['journal_entry']['lines']

    def test_then_the_invoice_itself_can_be_deleted(self, client, db_session, admin_user,
                                                    main_branch):
        """The order the SI delete asks for: the receipt first, then the invoice."""
        crv, si, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        _delete(client, crv.id)
        client.post(f'/sales-invoices/{si.id}/delete', data={'delete_reason': REASON},
                    follow_redirects=True)
        assert _si(si.id) is None

    def test_a_draft_receipt_can_be_deleted(self, client, db_session, admin_user, main_branch):
        si, cust, ar, rev, cash = _posted_si(client, db_session, admin_user, main_branch)
        crv = _pay(client, si, cust, cash, 2000, post=False)
        _delete(client, crv.id)
        assert CashReceiptVoucher.query.filter_by(crv_number='CR-AO-1').first() is None
        assert _si(si.id).amount_paid == Decimal('0.00')

    def test_a_voided_receipt_can_be_deleted(self, client, db_session, admin_user, main_branch):
        si, cust, ar, rev, cash = _posted_si(client, db_session, admin_user, main_branch)
        crv = _pay(client, si, cust, cash, 2000, post=False)
        client.post(f'/cash-receipts/{crv.id}/void', data={'void_reason': 'entered twice by mistake'},
                    follow_redirects=True)
        _delete(client, crv.id)
        assert CashReceiptVoucher.query.filter_by(crv_number='CR-AO-1').first() is None

    def test_a_cancelled_receipt_is_refused(self, client, db_session, admin_user, main_branch):
        crv, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        client.post(f'/cash-receipts/{crv.id}/cancel',
                    data={'cancel_reason': 'cheque bounced, receipt reversed',
                          'reversal_date': TODAY.isoformat()}, follow_redirects=True)
        db.session.expire_all()
        assert db.session.get(CashReceiptVoucher, crv.id).status == 'cancelled'
        body = _delete(client, crv.id).data.decode()
        assert 'cannot be deleted' in body
        assert db.session.get(CashReceiptVoucher, crv.id) is not None

    def test_a_reason_is_required(self, client, db_session, admin_user, main_branch):
        crv, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        body = _delete(client, crv.id, reason='too short').data.decode()
        assert 'reason of at least 10 characters' in body
        assert db.session.get(CashReceiptVoucher, crv.id) is not None

    def test_an_accountant_is_refused(self, client, db_session, admin_user, accountant_user,
                                      main_branch):
        crv, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/cash-receipts/{crv.id}/delete', data={'delete_reason': REASON})
        assert resp.status_code == 403
        assert db.session.get(CashReceiptVoucher, crv.id) is not None

    def test_a_closed_period_refuses(self, client, db_session, admin_user, main_branch):
        crv, si, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        _close_period(db_session, crv.crv_date)
        body = _delete(client, crv.id).data.decode()
        assert 'Cannot delete posted CRV' in body
        assert _si(si.id).amount_paid == Decimal('2000.00')

    def test_a_bank_reconciled_receipt_refuses(self, client, db_session, admin_user,
                                               main_branch):
        crv, si, cust, cash = _posted_crv(client, db_session, admin_user, main_branch)
        _reconcile(db_session, crv, cash, main_branch)
        _delete(client, crv.id)
        assert db.session.get(CashReceiptVoucher, crv.id) is not None
        assert _si(si.id).amount_paid == Decimal('2000.00')


class TestTheDetailPage:

    def test_the_administrator_sees_edit_and_delete(self, client, db_session, admin_user,
                                                    main_branch):
        crv, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        body = client.get(f'/cash-receipts/{crv.id}').data.decode()
        assert 'Edit (admin)' in body and f'/cash-receipts/{crv.id}/delete' in body

    def test_an_accountant_does_not(self, client, db_session, admin_user, accountant_user,
                                    main_branch):
        crv, *_ = _posted_crv(client, db_session, admin_user, main_branch)
        _login(client, accountant_user, main_branch)
        body = client.get(f'/cash-receipts/{crv.id}').data.decode()
        assert 'Edit (admin)' not in body and f'/cash-receipts/{crv.id}/delete' not in body
