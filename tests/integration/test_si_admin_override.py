"""The administrator may edit or delete a sales invoice after it is posted.

Owner, 2026-10-06: "we need to give admin the ultimate power now. allow admin to delete or
modify records even after its approved. we will do this document per document." CV came
first; SI next (owner, 2026-10-07: "build SI next"). The terms settled for every document
(app-docs/admin-override-checklist.md):

* admin only -- an accountant keeps today's rules;
* delete is a HARD delete: the invoice, its lines, its JE and its attachments leave the
  books, delivery receipts it billed reopen, and the number is free again;
* edit is IN PLACE: the invoice keeps its status, its JE is rebuilt under the same entry
  number and posting stamp;
* a reason (10+ characters) is required, and lands in the audit log;
* a closed period still refuses.

Specific to the SI: the payments on an invoice are other documents (cash receipt vouchers),
so an invoice a CRV applies to -- or a sales memo refers to -- is not deleted out from under
them; delete those first. An edit may not take the total below what is already collected,
nor move a paid invoice to another customer.
"""
import io
import json
import os
from datetime import date
from decimal import Decimal

import pytest
from flask import g

from app import db
from app.accounts.models import Account
from app.audit.models import AuditLog
from app.cash_receipts.models import CashReceiptVoucher
from app.customers.models import Customer
from app.journal_entries.models import JournalEntry
from app.sales_invoices.models import SalesInvoice, SalesInvoiceAttachment

pytestmark = [pytest.mark.integration, pytest.mark.sales_invoices]

REASON = 'Opening balance replaced by the actual unpaid ARDs'
TODAY = date.today()


# ------------------------------------------------------------------ helpers

def _login(client, user, branch):
    g.pop('_login_user', None)
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)
        s['_fresh'] = True
        s['selected_branch_id'] = branch.id


def _accounts(db_session):
    ar = Account(code='10201', name='Accounts Receivable - Trade', account_type='Asset',
                 normal_balance='debit', is_active=True)
    rev = Account(code='40101', name='Sales', account_type='Income', normal_balance='credit',
                  is_active=True)
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   normal_balance='debit', is_active=True)
    db_session.add_all([ar, rev, cash])
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return ar, rev, cash


def _customer(db_session, code='SIAO1', name='Override Customer'):
    c = Customer(code=code, name=name, is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _lines(rev, amount):
    return json.dumps([{'description': 'Dried mango', 'amount': amount, 'vat_category': '',
                        'account_id': rev.id, 'wt_id': None, 'wt_rate': None}])


def _form(invoice_number, customer, rev, amount, invoice_date=None, row_version=None,
          reason=None):
    d = (invoice_date or TODAY).isoformat()
    data = {'invoice_number': invoice_number, 'invoice_date': d, 'due_date': d,
            'customer_id': customer.id, 'payment_terms': 'Net 30', 'reference': '',
            'notes': 'particulars', 'line_items': _lines(rev, amount),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0'}
    if row_version is not None:
        data['row_version'] = row_version
    if reason is not None:
        data['admin_reason'] = reason
    return data


def _posted_si(client, db_session, admin_user, main_branch, amount=5000, number='SI-AO-1',
               customer=None, accounts=None):
    """A sales invoice created and posted through the real routes."""
    _login(client, admin_user, main_branch)
    ar, rev, cash = accounts or _accounts(db_session)
    customer = customer or _customer(db_session)
    client.post('/sales-invoices/create', data=_form(number, customer, rev, amount),
                follow_redirects=True)
    si = SalesInvoice.query.filter_by(invoice_number=number).first()
    assert si is not None, 'SI was not created'
    client.post(f'/sales-invoices/{si.id}/post', follow_redirects=True)
    db_session.refresh(si)
    assert si.status == 'posted'
    return si, customer, ar, rev, cash


def _edit(client, si, customer, rev, amount, reason=REASON, invoice_date=None):
    return client.post(f'/sales-invoices/{si.id}/edit',
                       data=_form(si.invoice_number, customer, rev, amount,
                                  invoice_date=invoice_date, row_version=si.row_version,
                                  reason=reason),
                       follow_redirects=True)


def _delete(client, si_id, reason=REASON):
    data = {} if reason is None else {'delete_reason': reason}
    return client.post(f'/sales-invoices/{si_id}/delete', data=data, follow_redirects=True)


def _pay(client, si, customer, cash, amount, number='CR-AO-1', post=True):
    """A cash receipt applied to *si* through the real routes."""
    client.post('/cash-receipts/create', data={
        'crv_number': number, 'crv_date': TODAY.isoformat(), 'customer_id': customer.id,
        'payment_method': 'cash', 'cash_account_id': cash.id, 'notes': 'collection',
        'ar_lines': json.dumps([{'invoice_id': si.id, 'invoice_number': si.invoice_number,
                                 'original_balance': float(si.balance),
                                 'amount_applied': amount}]),
        'revenue_lines': json.dumps([]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    crv = CashReceiptVoucher.query.filter_by(crv_number=number).first()
    assert crv is not None, 'CRV was not created'
    if post:
        client.post(f'/cash-receipts/{crv.id}/post', follow_redirects=True)
    db.session.expire_all()
    return crv


def _close_period(db_session, d):
    from app.periods.models import AccountingPeriod
    db_session.add(AccountingPeriod(year=d.year, month=d.month, status='closed'))
    db_session.commit()


def _audit(action, record_id):
    return (AuditLog.query.filter_by(module='sales_invoice', action=action, record_id=record_id)
            .order_by(AuditLog.id.desc()).first())


def _as_dict(v):
    return v if isinstance(v, dict) else json.loads(v or '{}')


def _ar_debit(je, ar):
    return next(l.debit_amount for l in je.lines if l.account_id == ar.id)


# ------------------------------------------------------------------ edit a posted SI

class TestAdminEditsAPostedInvoice:

    def test_the_invoice_is_corrected_in_place(self, client, db_session, admin_user, main_branch):
        si, cust, ar, rev, _ = _posted_si(client, db_session, admin_user, main_branch)
        je_number = si.journal_entry.entry_number
        posted_at = si.journal_entry.posted_at
        _edit(client, si, cust, rev, 6000)
        db.session.expire_all()
        si = db.session.get(SalesInvoice, si.id)
        assert si.status == 'posted'
        assert si.total_amount == Decimal('6000.00') and si.balance == Decimal('6000.00')
        assert JournalEntry.query.count() == 1
        je = si.journal_entry
        assert je.entry_number == je_number          # the same entry, corrected
        assert je.status == 'posted' and je.posted_at == posted_at
        assert _ar_debit(je, ar) == Decimal('6000.00')

    def test_the_edit_is_audited_with_its_reason(self, client, db_session, admin_user, main_branch):
        si, cust, _, rev, _ = _posted_si(client, db_session, admin_user, main_branch)
        _edit(client, si, cust, rev, 6000)
        row = _audit('admin_edit_posted', si.id)
        assert row is not None and REASON in row.notes
        assert _as_dict(row.old_values)['total_amount'] in ('5000.00', '5000', 5000.0, 5000)
        assert _as_dict(row.new_values)['total_amount'] in ('6000.00', '6000', 6000.0, 6000)

    def test_a_reason_is_required(self, client, db_session, admin_user, main_branch):
        si, cust, _, rev, _ = _posted_si(client, db_session, admin_user, main_branch)
        body = _edit(client, si, cust, rev, 6000, reason='short').data.decode()
        assert 'reason of at least 10 characters' in body
        db.session.expire_all()
        assert db.session.get(SalesInvoice, si.id).total_amount == Decimal('5000.00')

    def test_an_accountant_still_cannot_edit_a_posted_invoice(
            self, client, db_session, admin_user, accountant_user, main_branch):
        si, cust, _, rev, _ = _posted_si(client, db_session, admin_user, main_branch)
        _login(client, accountant_user, main_branch)
        _edit(client, si, cust, rev, 6000)
        db.session.expire_all()
        assert db.session.get(SalesInvoice, si.id).total_amount == Decimal('5000.00')

    def test_a_closed_period_refuses(self, client, db_session, admin_user, main_branch):
        si, cust, _, rev, _ = _posted_si(client, db_session, admin_user, main_branch)
        _close_period(db_session, si.invoice_date)
        body = _edit(client, si, cust, rev, 6000).data.decode()
        assert 'Cannot edit posted Sales Invoice' in body
        db.session.expire_all()
        assert db.session.get(SalesInvoice, si.id).total_amount == Decimal('5000.00')

    def test_the_edit_form_asks_for_the_reason(self, client, db_session, admin_user, main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        body = client.get(f'/sales-invoices/{si.id}/edit').data.decode()
        assert 'Edit Posted Sales Invoice (admin)' in body
        assert 'name="admin_reason"' in body


class TestAdminEditsAPaidInvoice:

    def test_a_part_paid_invoice_keeps_its_payment(self, client, db_session, admin_user,
                                                   main_branch):
        si, cust, ar, rev, cash = _posted_si(client, db_session, admin_user, main_branch)
        _pay(client, si, cust, cash, 2000)
        si = db.session.get(SalesInvoice, si.id)
        assert si.status == 'partially_paid'
        _edit(client, si, cust, rev, 6000)
        db.session.expire_all()
        si = db.session.get(SalesInvoice, si.id)
        assert si.amount_paid == Decimal('2000.00')
        assert si.balance == Decimal('4000.00') and si.status == 'partially_paid'
        assert si.journal_entry.status == 'posted'          # not demoted to draft
        assert _ar_debit(si.journal_entry, ar) == Decimal('6000.00')

    def test_cutting_a_paid_invoice_to_its_payment_makes_it_paid(
            self, client, db_session, admin_user, main_branch):
        si, cust, _, rev, cash = _posted_si(client, db_session, admin_user, main_branch)
        _pay(client, si, cust, cash, 2000)
        si = db.session.get(SalesInvoice, si.id)
        _edit(client, si, cust, rev, 2000)
        db.session.expire_all()
        si = db.session.get(SalesInvoice, si.id)
        assert si.balance == Decimal('0.00') and si.status == 'paid'

    def test_the_total_cannot_go_below_what_is_collected(self, client, db_session, admin_user,
                                                         main_branch):
        si, cust, _, rev, cash = _posted_si(client, db_session, admin_user, main_branch)
        _pay(client, si, cust, cash, 2000)
        si = db.session.get(SalesInvoice, si.id)
        body = _edit(client, si, cust, rev, 1500).data.decode()
        assert 'already collected' in body
        db.session.expire_all()
        assert db.session.get(SalesInvoice, si.id).total_amount == Decimal('5000.00')

    def test_a_paid_invoice_cannot_move_to_another_customer(self, client, db_session,
                                                            admin_user, main_branch):
        si, cust, _, rev, cash = _posted_si(client, db_session, admin_user, main_branch)
        _pay(client, si, cust, cash, 2000)
        other = _customer(db_session, code='SIAO2', name='Another Customer')
        si = db.session.get(SalesInvoice, si.id)
        body = _edit(client, si, other, rev, 5000).data.decode()
        assert 'another customer' in body
        db.session.expire_all()
        assert db.session.get(SalesInvoice, si.id).customer_id == cust.id


# ------------------------------------------------------------------ delete

class TestAdminDeletesAnInvoice:

    def test_a_posted_invoice_and_its_entry_leave_the_books(self, client, db_session,
                                                            admin_user, main_branch):
        si, cust, _, rev, _ = _posted_si(client, db_session, admin_user, main_branch)
        si_id, je_id = si.id, si.journal_entry_id
        _delete(client, si_id)
        db.session.expire_all()
        assert db.session.get(SalesInvoice, si_id) is None
        assert db.session.get(JournalEntry, je_id) is None

    def test_the_number_is_free_again(self, client, db_session, admin_user, main_branch):
        si, cust, _, rev, _ = _posted_si(client, db_session, admin_user, main_branch)
        _delete(client, si.id)
        client.post('/sales-invoices/create', data=_form('SI-AO-1', cust, rev, 100),
                    follow_redirects=True)
        reused = SalesInvoice.query.filter_by(invoice_number='SI-AO-1').all()
        assert [s.total_amount for s in reused] == [Decimal('100.00')]   # the new one only

    def test_the_delete_is_audited_with_a_snapshot(self, client, db_session, admin_user,
                                                   main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        si_id = si.id
        _delete(client, si_id)
        row = _audit('admin_delete', si_id)
        assert row is not None and REASON in row.notes
        snap = _as_dict(row.old_values)
        assert snap['invoice_number'] == 'SI-AO-1'
        assert snap['total_amount'] == '5000.00'
        assert snap['journal_entry']['lines']

    def test_a_draft_invoice_can_be_deleted(self, client, db_session, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        _, rev, _ = _accounts(db_session)
        cust = _customer(db_session)
        client.post('/sales-invoices/create', data=_form('SI-AO-D', cust, rev, 100),
                    follow_redirects=True)
        si = SalesInvoice.query.filter_by(invoice_number='SI-AO-D').first()
        _delete(client, si.id)
        assert SalesInvoice.query.filter_by(invoice_number='SI-AO-D').first() is None

    def test_a_voided_invoice_can_be_deleted(self, client, db_session, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        _, rev, _ = _accounts(db_session)
        cust = _customer(db_session)
        client.post('/sales-invoices/create', data=_form('SI-AO-V', cust, rev, 100),
                    follow_redirects=True)
        si = SalesInvoice.query.filter_by(invoice_number='SI-AO-V').first()
        client.post(f'/sales-invoices/{si.id}/void', data={'void_reason': 'entered twice by mistake'},
                    follow_redirects=True)
        _delete(client, si.id)
        assert SalesInvoice.query.filter_by(invoice_number='SI-AO-V').first() is None

    def test_a_cancelled_invoice_is_refused(self, client, db_session, admin_user, main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        client.post(f'/sales-invoices/{si.id}/cancel',
                    data={'cancel_reason': 'customer returned the goods',
                          'reversal_date': TODAY.isoformat()}, follow_redirects=True)
        db.session.expire_all()
        assert db.session.get(SalesInvoice, si.id).status == 'cancelled'
        body = _delete(client, si.id).data.decode()
        assert 'cannot be deleted' in body
        assert db.session.get(SalesInvoice, si.id) is not None

    def test_a_reason_is_required(self, client, db_session, admin_user, main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        body = _delete(client, si.id, reason='too short').data.decode()
        assert 'reason of at least 10 characters' in body
        assert db.session.get(SalesInvoice, si.id) is not None

    def test_an_accountant_is_refused(self, client, db_session, admin_user, accountant_user,
                                      main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/sales-invoices/{si.id}/delete', data={'delete_reason': REASON})
        assert resp.status_code == 403
        assert db.session.get(SalesInvoice, si.id) is not None

    def test_a_closed_period_refuses(self, client, db_session, admin_user, main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        _close_period(db_session, si.invoice_date)
        body = _delete(client, si.id).data.decode()
        assert 'Cannot delete posted Sales Invoice' in body
        assert db.session.get(SalesInvoice, si.id) is not None


class TestDeleteLeavesNoDocumentPointingAtNothing:

    def test_an_invoice_with_a_posted_receipt_is_refused(self, client, db_session, admin_user,
                                                         main_branch):
        si, cust, _, _, cash = _posted_si(client, db_session, admin_user, main_branch)
        _pay(client, si, cust, cash, 2000)
        body = _delete(client, si.id).data.decode()
        assert 'CR-AO-1' in body
        assert db.session.get(SalesInvoice, si.id) is not None

    def test_an_invoice_on_a_draft_receipt_is_refused(self, client, db_session, admin_user,
                                                      main_branch):
        si, cust, _, _, cash = _posted_si(client, db_session, admin_user, main_branch)
        _pay(client, si, cust, cash, 2000, post=False)
        body = _delete(client, si.id).data.decode()
        assert 'CR-AO-1' in body
        assert db.session.get(SalesInvoice, si.id) is not None

    def test_an_invoice_a_memo_refers_to_is_refused(self, client, db_session, admin_user,
                                                    main_branch):
        from app.sales_memos.models import SalesMemo
        si, cust, *_ = _posted_si(client, db_session, admin_user, main_branch)
        db_session.add(SalesMemo(
            branch_id=si.branch_id, memo_type='credit', memo_number='CM-AO-1', memo_date=TODAY,
            sales_invoice_id=si.id, original_invoice_number=si.invoice_number,
            customer_id=cust.id, customer_name=cust.name, reason='Price adjustment',
            notes='', destination='ar', subtotal=Decimal('100'), vat_amount=Decimal('0'),
            withholding_tax_amount=Decimal('0'), total_amount=Decimal('100'),
            amount_paid=Decimal('0'), balance=Decimal('100'), status='draft'))
        db_session.commit()
        body = _delete(client, si.id).data.decode()
        assert 'CM-AO-1' in body
        assert db.session.get(SalesInvoice, si.id) is not None

    def test_a_billed_delivery_receipt_reopens(self, client, db_session, admin_user, main_branch):
        from app.delivery_receipts.models import DeliveryReceipt
        from tests.integration.test_si_dr_billing import _create_si, _delivered_dr, _setup
        c, p, soi, rev = _setup(db_session, main_branch)
        dr = _delivered_dr(main_branch, c, p, soi, 'DR-AO-1')
        _login(client, admin_user, main_branch)
        _create_si(client, c, rev, [dr.id], number='SI-AO-DR')
        si = SalesInvoice.query.filter_by(invoice_number='SI-AO-DR').first()
        assert db.session.get(DeliveryReceipt, dr.id).sales_invoice_id == si.id
        _delete(client, si.id)
        db.session.expire_all()
        dr = db.session.get(DeliveryReceipt, dr.id)
        assert dr.status == 'delivered' and dr.sales_invoice_id is None

    def test_attachments_go_with_the_invoice(self, client, db_session, admin_user, main_branch,
                                             app):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        client.post(f'/sales-invoices/{si.id}/attachments/upload',
                    data={'attachment': (io.BytesIO(b'%PDF-1.4 ard copy'), 'ard.pdf')},
                    content_type='multipart/form-data', follow_redirects=True)
        att = SalesInvoiceAttachment.query.filter_by(invoice_id=si.id).first()
        assert att is not None, 'the administrator could not attach to the posted invoice'
        path = os.path.join(app.config['UPLOAD_FOLDER'], 'sales_invoices', str(si.id),
                            att.stored_filename)
        assert os.path.exists(path)
        _delete(client, si.id)
        assert SalesInvoiceAttachment.query.filter_by(invoice_id=si.id).count() == 0
        assert not os.path.exists(path)


# ------------------------------------------------------------------ attachments, buttons

class TestAttachmentsAfterPosting:

    def test_an_accountant_still_cannot_attach_to_a_posted_invoice(
            self, client, db_session, admin_user, accountant_user, main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        _login(client, accountant_user, main_branch)
        client.post(f'/sales-invoices/{si.id}/attachments/upload',
                    data={'attachment': (io.BytesIO(b'%PDF-1.4 x'), 'x.pdf')},
                    content_type='multipart/form-data', follow_redirects=True)
        assert SalesInvoiceAttachment.query.filter_by(invoice_id=si.id).count() == 0


class TestTheDetailPage:

    def test_the_administrator_sees_edit_and_delete(self, client, db_session, admin_user,
                                                    main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        body = client.get(f'/sales-invoices/{si.id}').data.decode()
        assert 'Edit (admin)' in body
        assert f'/sales-invoices/{si.id}/delete' in body

    def test_an_accountant_does_not(self, client, db_session, admin_user, accountant_user,
                                    main_branch):
        si, *_ = _posted_si(client, db_session, admin_user, main_branch)
        _login(client, accountant_user, main_branch)
        body = client.get(f'/sales-invoices/{si.id}').data.decode()
        assert 'Edit (admin)' not in body
        assert f'/sales-invoices/{si.id}/delete' not in body
