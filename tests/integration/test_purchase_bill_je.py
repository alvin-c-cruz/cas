"""Integration tests — purchase JE auto-posted on bill create/edit."""
import json
import pytest
from decimal import Decimal
from datetime import date
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='JEV001'):
    v = Vendor(code=code, name='JE Test Vendor', check_payee_name='JE Test Vendor',
               is_active=True, payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def get_or_create_account(db_session, code, name, acct_type):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=acct_type,
                    normal_balance='debit' if acct_type == 'Expense' else 'credit',
                    is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def make_line_items_payload(amount=11200.00, vat_code='', account_id=None,
                             wt_id=None, wt_rate=None):
    return json.dumps([{
        'description': 'Test Service',
        'amount': amount,
        'vat_category': vat_code,
        'account_id': account_id,
        'wt_id': wt_id,
        'wt_rate': wt_rate,
    }])


class TestBillCreatePostsJE:
    def test_create_bill_posts_je_with_purchase_type(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        vendor = make_vendor(db_session)

        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        vat_acct = get_or_create_account(db_session, '10501', 'Input VAT - Current', 'Asset')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        vat_cat = VATCategory(code='VAT12', name='VAT 12%', rate=Decimal('12'), is_active=True)
        db_session.add(vat_cat)
        db_session.commit()

        resp = client.post('/purchase-bills/create', data={
            'bill_number': 'PBJ-001',
            'bill_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'line_items': make_line_items_payload(
                amount=11200.00, vat_code='VAT12', account_id=exp.id),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        assert resp.status_code == 200

        bill = PurchaseBill.query.filter_by(bill_number='PBJ-001').first()
        assert bill is not None
        assert bill.journal_entry_id is not None

        je = db_session.get(JournalEntry, bill.journal_entry_id)
        assert je is not None
        assert je.entry_type == 'purchase'
        assert je.status == 'posted'
        assert je.is_balanced is True

    def test_je_lines_correct_for_12pct_vat(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='JEV002')

        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        vat_acct = get_or_create_account(db_session, '10501', 'Input VAT - Current', 'Asset')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        vat_cat = VATCategory(code='VAT12B', name='VAT 12%', rate=Decimal('12'), is_active=True)
        db_session.add(vat_cat)
        db_session.commit()

        client.post('/purchase-bills/create', data={
            'bill_number': 'PBJ-002',
            'bill_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'line_items': make_line_items_payload(
                amount=11200.00, vat_code='VAT12B', account_id=exp.id),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        bill = PurchaseBill.query.filter_by(bill_number='PBJ-002').first()
        assert bill is not None, "Bill PBJ-002 not created"
        je = db_session.get(JournalEntry, bill.journal_entry_id)
        lines = JournalEntryLine.query.filter_by(entry_id=je.id).all()

        # Dr Expense (net_base = 11200/1.12 = 10000)
        exp_line = next((l for l in lines if l.account_id == exp.id), None)
        assert exp_line is not None
        assert exp_line.debit_amount == Decimal('10000.00')

        # Dr Input VAT (1200)
        vat_line = next((l for l in lines if l.account_id == vat_acct.id), None)
        assert vat_line is not None
        assert vat_line.debit_amount == Decimal('1200.00')

        # Cr AP (11200 — no WHT)
        ap_line = next((l for l in lines if l.account_id == ap.id), None)
        assert ap_line is not None
        assert ap_line.credit_amount == Decimal('11200.00')

        # JE balances
        total_dr = sum(l.debit_amount for l in lines)
        total_cr = sum(l.credit_amount for l in lines)
        assert total_dr == total_cr

    def test_edit_bill_recreates_je(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='JEV003')
        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        # Create the bill
        client.post('/purchase-bills/create', data={
            'bill_number': 'PBJ-003',
            'bill_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'line_items': make_line_items_payload(
                amount=5000.00, vat_code='', account_id=exp.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        bill = PurchaseBill.query.filter_by(bill_number='PBJ-003').first()
        assert bill is not None, "Bill PBJ-003 not created"
        old_je_id = bill.journal_entry_id
        assert old_je_id is not None

        # Edit the bill
        client.post(f'/purchase-bills/{bill.id}/edit', data={
            'bill_number': 'PBJ-003',
            'bill_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'line_items': make_line_items_payload(
                amount=6000.00, vat_code='', account_id=exp.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        db_session.expire_all()
        bill = PurchaseBill.query.filter_by(bill_number='PBJ-003').first()
        new_je_id = bill.journal_entry_id
        assert new_je_id is not None

        # There must be exactly one JE in the DB (old was deleted, new was created).
        # SQLite may reuse the same integer ID, so we assert count rather than ID inequality.
        je_count = JournalEntry.query.count()
        assert je_count == 1, f"Expected 1 JE after edit, found {je_count}"

        new_je = db_session.get(JournalEntry, new_je_id)
        assert new_je is not None
        # Verify the JE reflects the edited amount (6000, not 5000)
        ap_line = next((l for l in new_je.lines if l.account_id == ap.id), None)
        assert ap_line is not None
        assert ap_line.credit_amount == Decimal('6000.00')
