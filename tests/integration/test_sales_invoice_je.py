"""Regression tests — SI JE is recreated correctly on edit.

Covers commit a7b63f0: db.session.expire(invoice, ['line_items']) after
Query.delete() ensures calculate_totals() and _post_invoice_je() see fresh
lines, not the stale ORM cache.
"""
import json
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
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


def make_customer(db_session, code='SIJEC001'):
    c = Customer(code=code, name='SI JE Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def make_line_items_payload(amount, account_id):
    return json.dumps([{
        'description': 'Test Service',
        'amount': amount,
        'vat_category': '',
        'account_id': account_id,
        'wt_id': None,
        'wt_rate': None,
    }])


class TestSIEditRecreatesJE:
    def test_edit_invoice_recreates_je(
            self, client, db_session, accountant_user, main_branch):
        """Editing a draft SI deletes the old JE and creates a new one reflecting the new amount."""
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        ar = get_or_create_account(db_session, '10201', 'Accounts Receivable - Trade',
                                   'Asset', 'debit')
        rev = get_or_create_account(db_session, 'SI-JE-REV1', 'SI JE Revenue',
                                    'Revenue', 'credit')

        # Create invoice at 5000
        client.post('/sales-invoices/create', data={
            'invoice_number': 'SIJE-001',
            'invoice_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'customer_id': make_customer(db_session, 'SIJEC-001').id,
            'payment_terms': 'Net 30',
            'reference': '',
            'notes': 'Test particulars',
            'line_items': make_line_items_payload(5000.00, rev.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        invoice = SalesInvoice.query.order_by(SalesInvoice.id.desc()).first()
        assert invoice is not None, "Invoice SIJE-001 was not created"
        old_je_id = invoice.journal_entry_id
        assert old_je_id is not None, "No JE created on invoice create"

        # Edit invoice to 6000
        client.post(f'/sales-invoices/{invoice.id}/edit', data={
            'invoice_number': 'SIJE-001',
            'invoice_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'customer_id': invoice.customer_id,
            'payment_terms': 'Net 30',
            'reference': '',
            'notes': 'Test particulars',
            'line_items': make_line_items_payload(6000.00, rev.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        db_session.expire_all()
        invoice = SalesInvoice.query.order_by(SalesInvoice.id.desc()).first()
        new_je_id = invoice.journal_entry_id
        assert new_je_id is not None, "JE missing after edit"

        je_count = JournalEntry.query.count()
        assert je_count == 1, f"Expected 1 JE after edit, found {je_count}"

        new_je = db_session.get(JournalEntry, new_je_id)
        assert new_je is not None

        ar_line = next((l for l in new_je.lines if l.account_id == ar.id), None)
        assert ar_line is not None, "AR debit line missing from recreated JE"
        assert ar_line.debit_amount == Decimal('6000.00'), (
            f"JE AR line should be 6000 after edit; got {ar_line.debit_amount}")

    def test_edit_invoice_subtotal_reflects_new_amount(
            self, client, db_session, accountant_user, main_branch):
        """Regression: invoice.subtotal/total_amount must be recomputed from NEW lines.

        Without db.session.expire(invoice, ['line_items']), calculate_totals() iterates
        the stale ORM cache (old lines already deleted) and commits wrong totals.
        """
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        get_or_create_account(db_session, '10201', 'Accounts Receivable - Trade',
                               'Asset', 'debit')
        rev = get_or_create_account(db_session, 'SI-JE-REV2', 'SI JE Revenue 2',
                                    'Revenue', 'credit')
        customer = make_customer(db_session, 'SIJEC-002')

        # Create at 5000
        client.post('/sales-invoices/create', data={
            'invoice_number': 'SIJE-002',
            'invoice_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'customer_id': customer.id,
            'payment_terms': 'Net 30',
            'reference': '',
            'notes': 'Test particulars',
            'line_items': make_line_items_payload(5000.00, rev.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        invoice = SalesInvoice.query.filter_by(invoice_number='SIJE-002').first()
        assert invoice is not None, "Invoice SIJE-002 was not created"

        # Edit to 6000
        client.post(f'/sales-invoices/{invoice.id}/edit', data={
            'invoice_number': 'SIJE-002',
            'invoice_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'customer_id': customer.id,
            'payment_terms': 'Net 30',
            'reference': '',
            'notes': 'Test particulars',
            'line_items': make_line_items_payload(6000.00, rev.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        db_session.expire_all()
        invoice = SalesInvoice.query.filter_by(invoice_number='SIJE-002').first()
        assert invoice.subtotal == Decimal('6000.00'), (
            f"invoice.subtotal should be 6000 after edit; got {invoice.subtotal}")
        assert invoice.total_amount == Decimal('6000.00'), (
            f"invoice.total_amount should be 6000 after edit; got {invoice.total_amount}")
