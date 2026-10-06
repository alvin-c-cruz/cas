"""The administrator may edit or delete a cash voucher after it is posted.

Owner, 2026-10-06: "we need to give admin the ultimate power now. allow admin to delete or
modify records even after its approved. we will do this document per document. starting
with CV." Settled with the owner the same day:

* admin only -- an accountant keeps today's rules;
* delete is a HARD delete: the voucher, its lines and its JE leave the books, the bills it
  paid reopen, receipts it settled reopen, and the number is free again;
* edit is IN PLACE: the voucher stays posted, its JE is rebuilt under the same entry
  number, and the bill payments are re-applied from the edited lines;
* a reason (10+ characters) is required, and lands in the audit log;
* a closed period still refuses -- reopen it first. So do a bank-reconciled JE line and a
  fixed-asset tag on one of the voucher's lines.

This deliberately relaxes "posted documents are never edited" (CAS-DEVELOPMENT.md) for
the administrator only.
"""
import json
from datetime import date
from decimal import Decimal

import pytest
from flask import g

from app.accounts.models import Account
from app.attachments.registry import can_delete, can_upload, get_target
from app.audit.models import AuditLog
from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.utils import ph_now
from tests.integration.test_cdv_views import (create_draft_cdv, login, make_posted_bill,
                                              make_vendor, setup_accounts)
from tests.integration.test_receiving_reports_lifecycle import _login

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]

REASON = 'Wrong amount encoded, corrected per the signed CV'


# ------------------------------------------------------------------ helpers

def _posted_cdv(client, db_session, amount=5000.0):
    """A bill of 5,000 paid in full (or in part) by a CDV posted through the real routes."""
    login(client)
    ap, wt, cash, exp = setup_accounts(db_session)
    vendor = make_vendor(db_session)
    bill = make_posted_bill(db_session, vendor, ap, None or _branch_id(db_session))
    lines = [{'bill_id': bill.id, 'bill_number': bill.ap_number,
              'original_balance': 5000.0, 'amount_applied': amount}]
    create_draft_cdv(client, vendor, cash, ap_lines=lines)
    cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
    client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)
    db_session.refresh(cdv)
    assert cdv.status == 'posted'
    return cdv, bill, vendor, cash, exp


def _branch_id(db_session):
    from app.branches.models import Branch
    return Branch.query.first().id


def _edit(client, cdv, vendor, cash, amount=None, reason=REASON, notes=None, ap_lines=None,
          expense_lines=None):
    if ap_lines is None:
        ap_lines = [{'bill_id': l.ap_id, 'bill_number': l.ap_number,
                     'original_balance': float(l.original_balance),
                     'amount_applied': float(amount if amount is not None else l.amount_applied)}
                    for l in cdv.ap_lines]
    data = {
        'cdv_number': cdv.cdv_number,
        'cdv_date': cdv.cdv_date.isoformat(),
        'vendor_id': vendor.id,
        'payment_method': 'cash',
        'cash_account_id': cash.id,
        'notes': notes if notes is not None else cdv.notes,
        'row_version': cdv.row_version,
        'ap_lines': json.dumps(ap_lines),
        'expense_lines': json.dumps(expense_lines or []),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }
    if reason is not None:
        data['admin_reason'] = reason
    return client.post(f'/cash-disbursements/{cdv.id}/edit', data=data, follow_redirects=True)


def _delete(client, cdv_id, reason=REASON):
    data = {} if reason is None else {'delete_reason': reason}
    return client.post(f'/cash-disbursements/{cdv_id}/delete', data=data, follow_redirects=True)


def _as_accountant(client, accountant_user, main_branch):
    g.pop('_login_user', None)
    _login(client, accountant_user, main_branch)


def _close_period(db_session, d):
    from app.periods.models import AccountingPeriod
    db_session.add(AccountingPeriod(year=d.year, month=d.month, status='closed'))
    db_session.commit()


def _audit(action, record_id):
    return (AuditLog.query.filter_by(module='cash_disbursement', action=action,
                                     record_id=record_id)
            .order_by(AuditLog.id.desc()).first())


def _as_dict(v):
    return v if isinstance(v, dict) else json.loads(v or '{}')


def _reconcile(db_session, cdv, cash, main_branch):
    """Clear the voucher's cash line in a bank reconciliation."""
    from app.bank_accounts.models import BankAccount
    from app.bank_reconciliation.models import BankReconciliation, ReconciliationItem
    bank = BankAccount(branch_id=main_branch.id, code='CBC919', name='CBC 919',
                       account_id=cash.id)
    db_session.add(bank)
    db_session.flush()
    rec = BankReconciliation(bank_account_id=bank.id, statement_date=date.today(),
                             statement_ending_balance=Decimal('0'),
                             beginning_balance=Decimal('0'))
    db_session.add(rec)
    db_session.flush()
    line = JournalEntryLine.query.filter_by(entry_id=cdv.journal_entry_id,
                                            account_id=cash.id).first()
    db_session.add(ReconciliationItem(reconciliation_id=rec.id, je_line_id=line.id))
    db_session.commit()


def _settle_rr(db_session, cdv, vendor, main_branch):
    from tests.integration.test_rr_settled_by_cdv import _approved_rr
    rr = _approved_rr(db_session, main_branch, vendor)
    rr.status = 'billed'
    rr.settled_cdv_id = cdv.id
    rr.settle_reason = 'paid by this voucher before the AP module'
    db_session.commit()
    return rr


# ------------------------------------------------------------------ edit

class TestAdminEditsAPostedVoucher:

    def test_a_changed_amount_is_reapplied_to_the_bill(
            self, client, db_session, admin_user, main_branch):
        cdv, bill, vendor, cash, _ = _posted_cdv(client, db_session)
        je_number = cdv.journal_entry.entry_number

        _edit(client, cdv, vendor, cash, amount=3000)

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.status == 'posted'
        assert cdv.total_amount == Decimal('3000.00')
        assert (bill.amount_paid, bill.balance, bill.status) == (
            Decimal('3000.00'), Decimal('2000.00'), 'partially_paid')
        je = cdv.journal_entry
        assert je.status == 'posted'
        assert je.entry_number == je_number, 'the JE keeps its number'
        assert Decimal(str(je.total_debit)) == Decimal('3000.00') == Decimal(str(je.total_credit))

    def test_an_unchanged_amount_is_not_refused_as_an_overpayment(
            self, client, db_session, admin_user, main_branch):
        """The bill already shows this voucher's payment. Validating the edited lines
        against that balance would call every posted edit an overpayment."""
        cdv, bill, vendor, cash, _ = _posted_cdv(client, db_session)

        _edit(client, cdv, vendor, cash, notes='Particulars corrected')

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.notes == 'Particulars corrected'
        assert (bill.amount_paid, bill.balance, bill.status) == (
            Decimal('5000.00'), Decimal('0.00'), 'paid')
        assert JournalEntry.query.filter_by(entry_type='cash_disbursement').count() <= 1 or \
            cdv.journal_entry.status == 'posted'

    def test_the_original_posting_stamp_is_kept(
            self, client, db_session, admin_user, main_branch):
        cdv, _, vendor, cash, _ = _posted_cdv(client, db_session)
        posted_by, posted_at = cdv.posted_by_id, cdv.posted_at

        _edit(client, cdv, vendor, cash, amount=4000)

        db_session.refresh(cdv)
        assert (cdv.posted_by_id, cdv.posted_at) == (posted_by, posted_at)

    def test_an_overpayment_is_still_refused(
            self, client, db_session, admin_user, main_branch):
        cdv, bill, vendor, cash, _ = _posted_cdv(client, db_session)

        _edit(client, cdv, vendor, cash, amount=6000)

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.total_amount == Decimal('5000.00')
        assert (bill.amount_paid, bill.status) == (Decimal('5000.00'), 'paid')

    def test_a_reason_is_required(self, client, db_session, admin_user, main_branch):
        cdv, bill, vendor, cash, _ = _posted_cdv(client, db_session)

        resp = _edit(client, cdv, vendor, cash, amount=3000, reason='short')

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.total_amount == Decimal('5000.00')
        assert bill.status == 'paid'
        assert b'reason' in resp.data.lower()

    def test_the_edit_is_audited_with_its_reason(
            self, client, db_session, admin_user, main_branch):
        cdv, _, vendor, cash, _ = _posted_cdv(client, db_session)

        _edit(client, cdv, vendor, cash, amount=3000)

        row = _audit('admin_edit_posted', cdv.id)
        assert row is not None
        assert REASON in (row.notes or '')
        assert _as_dict(row.old_values)['total_amount'] != _as_dict(row.new_values)['total_amount']

    def test_the_audit_diff_shows_particulars_and_lines(
            self, client, db_session, admin_user, main_branch):
        """A particulars-only correction must not log identical before/after values."""
        cdv, _, vendor, cash, _ = _posted_cdv(client, db_session)

        _edit(client, cdv, vendor, cash, amount=4000, notes='Particulars corrected')

        row = _audit('admin_edit_posted', cdv.id)
        old, new = _as_dict(row.old_values), _as_dict(row.new_values)
        assert (old['notes'], new['notes']) == ('Test CDV particulars', 'Particulars corrected')
        assert old['lines'] != new['lines']
        assert '4000' in new['lines']

    def test_an_accountant_cannot_edit_a_posted_voucher(
            self, client, db_session, admin_user, accountant_user, main_branch):
        cdv, bill, vendor, cash, _ = _posted_cdv(client, db_session)
        _as_accountant(client, accountant_user, main_branch)

        _edit(client, cdv, vendor, cash, amount=3000)

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.total_amount == Decimal('5000.00')
        assert bill.status == 'paid'

    def test_a_closed_period_refuses(self, client, db_session, admin_user, main_branch):
        cdv, bill, vendor, cash, _ = _posted_cdv(client, db_session)
        _close_period(db_session, cdv.cdv_date)

        _edit(client, cdv, vendor, cash, amount=3000)

        db_session.refresh(cdv)
        db_session.refresh(bill)
        assert cdv.total_amount == Decimal('5000.00')
        assert bill.status == 'paid'

    def test_a_bank_reconciled_voucher_refuses(
            self, client, db_session, admin_user, main_branch):
        cdv, bill, vendor, cash, _ = _posted_cdv(client, db_session)
        _reconcile(db_session, cdv, cash, main_branch)

        resp = _edit(client, cdv, vendor, cash, amount=3000)

        db_session.refresh(cdv)
        assert cdv.total_amount == Decimal('5000.00')
        assert b'reconcil' in resp.data.lower()

    def test_a_payee_change_reopens_receipts_the_voucher_settled(
            self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        from app.vendors.models import Vendor
        other = Vendor(code='OTH02', name='Other Payee', check_payee_name='Other Payee',
                       is_active=True)
        db_session.add(other)
        db_session.commit()
        create_draft_cdv(client, vendor, cash, expense_lines=[
            {'description': 'Valve', 'amount': 1000.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': None}])
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
        client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)
        db_session.refresh(cdv)
        rr = _settle_rr(db_session, cdv, vendor, main_branch)

        _edit(client, cdv, other, cash, ap_lines=[], expense_lines=[
            {'description': 'Valve', 'amount': 1000.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': None}])

        db_session.refresh(cdv)
        db_session.refresh(rr)
        assert cdv.vendor_id == other.id
        assert (rr.status, rr.settled_cdv_id) == ('approved', None)


# ------------------------------------------------------------------ delete

class TestAdminDeletesAVoucher:

    def test_a_posted_voucher_is_removed_and_its_bill_reopens(
            self, client, db_session, admin_user, main_branch):
        cdv, bill, *_ = _posted_cdv(client, db_session)
        cdv_id, je_id = cdv.id, cdv.journal_entry_id

        _delete(client, cdv_id)

        db_session.expire_all()
        assert db_session.get(CashDisbursementVoucher, cdv_id) is None
        assert db_session.get(JournalEntry, je_id) is None
        assert CDVApLine.query.filter_by(cdv_id=cdv_id).count() == 0
        db_session.refresh(bill)
        assert (bill.amount_paid, bill.balance, bill.status) == (
            Decimal('0.00'), Decimal('5000.00'), 'posted')

    def test_the_number_is_free_again(self, client, db_session, admin_user, main_branch):
        cdv, _, vendor, cash, exp = _posted_cdv(client, db_session)
        number = cdv.cdv_number

        _delete(client, cdv.id)
        create_draft_cdv(client, vendor, cash, cdv_number=number, expense_lines=[
            {'description': 'Re-entered', 'amount': 100.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': None}])

        assert CashDisbursementVoucher.query.filter_by(cdv_number=number).count() == 1

    def test_a_reason_is_required(self, client, db_session, admin_user, main_branch):
        cdv, bill, *_ = _posted_cdv(client, db_session)

        _delete(client, cdv.id, reason=None)

        assert db_session.get(CashDisbursementVoucher, cdv.id) is not None
        db_session.refresh(bill)
        assert bill.status == 'paid'

    def test_the_delete_is_audited_with_a_snapshot(
            self, client, db_session, admin_user, main_branch):
        cdv, bill, *_ = _posted_cdv(client, db_session)
        cdv_id, number = cdv.id, cdv.cdv_number

        _delete(client, cdv_id)

        row = _audit('admin_delete', cdv_id)
        assert row is not None
        assert REASON in (row.notes or '')
        snap = _as_dict(row.old_values)
        assert snap['cdv_number'] == number
        assert snap['ap_lines'][0]['ap_number'] == bill.ap_number
        assert snap['journal_entry']['lines'], 'the deleted JE lines are kept in the log'

    def test_an_accountant_is_refused(
            self, client, db_session, admin_user, accountant_user, main_branch):
        cdv, bill, *_ = _posted_cdv(client, db_session)
        _as_accountant(client, accountant_user, main_branch)

        resp = client.post(f'/cash-disbursements/{cdv.id}/delete',
                           data={'delete_reason': REASON})

        assert resp.status_code == 403
        assert db_session.get(CashDisbursementVoucher, cdv.id) is not None

    def test_a_cancelled_voucher_is_refused(
            self, client, db_session, admin_user, main_branch):
        cdv, *_ = _posted_cdv(client, db_session)
        client.post(f'/cash-disbursements/{cdv.id}/cancel', data={
            'cancel_reason': 'Paid the wrong vendor, reversing',
            'reversal_date': ph_now().date().isoformat()}, follow_redirects=True)

        _delete(client, cdv.id)

        assert db_session.get(CashDisbursementVoucher, cdv.id) is not None

    def test_a_draft_voucher_can_be_deleted(
            self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)
        create_draft_cdv(client, vendor, cash, expense_lines=[
            {'description': 'Draft', 'amount': 100.0, 'vat_category': '',
             'account_id': exp.id, 'wt_id': None}])
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
        cdv_id, je_id = cdv.id, cdv.journal_entry_id

        _delete(client, cdv_id)

        db_session.expire_all()
        assert db_session.get(CashDisbursementVoucher, cdv_id) is None
        assert je_id is None or db_session.get(JournalEntry, je_id) is None

    def test_a_closed_period_refuses(self, client, db_session, admin_user, main_branch):
        cdv, *_ = _posted_cdv(client, db_session)
        _close_period(db_session, cdv.cdv_date)

        _delete(client, cdv.id)

        assert db_session.get(CashDisbursementVoucher, cdv.id) is not None

    def test_a_bank_reconciled_voucher_refuses(
            self, client, db_session, admin_user, main_branch):
        cdv, bill, vendor, cash, _ = _posted_cdv(client, db_session)
        _reconcile(db_session, cdv, cash, main_branch)

        _delete(client, cdv.id)

        assert db_session.get(CashDisbursementVoucher, cdv.id) is not None

    def test_receipts_the_voucher_settled_reopen(
            self, client, db_session, admin_user, main_branch):
        cdv, bill, vendor, *_ = _posted_cdv(client, db_session)
        rr = _settle_rr(db_session, cdv, vendor, main_branch)

        _delete(client, cdv.id)

        db_session.refresh(rr)
        assert (rr.status, rr.settled_cdv_id) == ('approved', None)

    def test_its_attachments_go_with_it(
            self, client, db_session, admin_user, main_branch, app, tmp_path):
        from app.attachments.models import DocumentAttachment
        cdv, *_ = _posted_cdv(client, db_session)
        app.config['UPLOAD_FOLDER'] = str(tmp_path)
        folder = tmp_path / 'cash_disbursements' / str(cdv.id)
        folder.mkdir(parents=True)
        (folder / 'abc123.pdf').write_bytes(b'%PDF-1.4 signed cv')
        db_session.add(DocumentAttachment(document_type='cash_disbursements', document_id=cdv.id,
                                          original_filename='signed cv.pdf',
                                          stored_filename='abc123.pdf',
                                          mime_type='application/pdf', file_size=18,
                                          kind='signed_cv', uploaded_by_id=admin_user.id))
        db_session.commit()

        _delete(client, cdv.id)

        assert DocumentAttachment.query.filter_by(document_type='cash_disbursements',
                                                  document_id=cdv.id).count() == 0
        assert not (folder / 'abc123.pdf').exists()


# ------------------------------------------------------------------ the buttons

class TestTheDetailPage:

    def test_the_admin_sees_edit_and_delete_on_a_posted_voucher(
            self, client, db_session, admin_user, main_branch):
        cdv, *_ = _posted_cdv(client, db_session)

        body = client.get(f'/cash-disbursements/{cdv.id}').data.decode()

        assert f'href="/cash-disbursements/{cdv.id}/edit"' in body
        assert f'action="/cash-disbursements/{cdv.id}/delete"' in body

    def test_an_accountant_does_not(
            self, client, db_session, admin_user, accountant_user, main_branch):
        cdv, *_ = _posted_cdv(client, db_session)
        _as_accountant(client, accountant_user, main_branch)

        body = client.get(f'/cash-disbursements/{cdv.id}').data.decode()

        assert f'href="/cash-disbursements/{cdv.id}/edit"' not in body
        assert f'action="/cash-disbursements/{cdv.id}/delete"' not in body

    def test_the_edit_form_asks_for_a_reason_on_a_posted_voucher(
            self, client, db_session, admin_user, main_branch):
        cdv, *_ = _posted_cdv(client, db_session)

        body = client.get(f'/cash-disbursements/{cdv.id}/edit').data.decode()

        assert 'name="admin_reason"' in body

    def test_the_edit_page_does_not_call_a_posted_voucher_a_draft(
            self, client, db_session, admin_user, main_branch):
        cdv, *_ = _posted_cdv(client, db_session)

        body = client.get(f'/cash-disbursements/{cdv.id}/edit').data.decode()

        assert '<title>Edit Posted CDV (admin)' in body or 'Edit Posted CDV (admin)</title>' in body
        assert 'Update Draft CDV' not in body


# ------------------------------------------------------------------ attachments

class TestAttachmentsAfterPosting:

    def test_the_admin_may_upload_and_delete_on_a_posted_voucher(
            self, client, db_session, admin_user, accountant_user, main_branch):
        cdv, *_ = _posted_cdv(client, db_session)
        target = get_target('cash_disbursements')

        class _Att:
            uploaded_by_id = accountant_user.id

        assert can_upload(target, cdv, admin_user)
        assert can_delete(target, cdv, admin_user, _Att())

    def test_an_accountant_keeps_todays_rule(
            self, client, db_session, admin_user, accountant_user, main_branch):
        cdv, *_ = _posted_cdv(client, db_session)
        target = get_target('cash_disbursements')

        assert not can_upload(target, cdv, accountant_user)
