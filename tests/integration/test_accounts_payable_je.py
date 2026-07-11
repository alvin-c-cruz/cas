"""Integration tests — purchase JE auto-posted on bill create/edit."""
import json
import pytest
from decimal import Decimal
from datetime import date
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax
pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]




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
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)
        vat_acct = get_or_create_account(db_session, '10501', 'Input VAT - Current', 'Asset')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        vat_cat = VATCategory(code='VAT12', name='VAT 12%', rate=Decimal('12'), is_active=True,
                              input_vat_account_id=vat_acct.id)
        db_session.add(vat_cat)
        db_session.commit()

        resp = client.post('/accounts-payable/create', data={
            'ap_number': 'PBJ-001',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items_payload(
                amount=11200.00, vat_code='VAT12', account_id=exp.id),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        assert resp.status_code == 200

        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
        assert bill is not None
        assert bill.journal_entry_id is not None

        je = db_session.get(JournalEntry, bill.journal_entry_id)
        assert je is not None
        assert je.entry_type == 'purchase'
        # B-018: a draft bill's JE stays draft until the bill is posted,
        # so unposted vouchers never appear in GL-based reports
        assert je.status == 'draft'
        assert je.is_balanced is True

    def test_je_lines_correct_for_12pct_vat(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='JEV002')

        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)
        vat_acct = get_or_create_account(db_session, '10501', 'Input VAT - Current', 'Asset')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        vat_cat = VATCategory(code='VAT12B', name='VAT 12%', rate=Decimal('12'), is_active=True,
                              input_vat_account_id=vat_acct.id)
        db_session.add(vat_cat)
        db_session.commit()

        client.post('/accounts-payable/create', data={
            'ap_number': 'PBJ-002',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items_payload(
                amount=11200.00, vat_code='VAT12B', account_id=exp.id),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
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

    def test_multi_line_rounding_residual_je_balances(
            self, client, db_session, accountant_user, main_branch):
        """3 lines at 100.01 with 12% VAT — per-line rounding must not unbalance the JE."""
        login(client)
        vendor = make_vendor(db_session, code='JEV004')

        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)
        vat_acct = get_or_create_account(db_session, '10501', 'Input VAT - Current', 'Asset')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        vat_cat = VATCategory(code='VAT12R', name='VAT 12%', rate=Decimal('12'), is_active=True,
                              input_vat_account_id=vat_acct.id)
        db_session.add(vat_cat)
        db_session.commit()

        line_items = json.dumps([
            {'description': f'Rounding line {i}', 'amount': 100.01,
             'vat_category': 'VAT12R', 'account_id': exp.id,
             'wt_id': None, 'wt_rate': None}
            for i in range(1, 4)
        ])

        resp = client.post('/accounts-payable/create', data={
            'ap_number': 'PBJ-004',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': line_items,
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)
        assert resp.status_code == 200

        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
        assert bill is not None, "Bill PBJ-004 not created (JE likely failed to balance)"
        assert bill.journal_entry_id is not None

        je = db_session.get(JournalEntry, bill.journal_entry_id)
        assert je is not None
        assert je.is_balanced is True
        assert je.total_debit == je.total_credit

        lines = JournalEntryLine.query.filter_by(entry_id=je.id).all()
        total_dr = sum(l.debit_amount for l in lines)
        total_cr = sum(l.credit_amount for l in lines)
        assert total_dr == total_cr
        # Cr AP must equal the bill total (3 x 100.01, no WHT)
        ap_line = next((l for l in lines if l.account_id == ap.id), None)
        assert ap_line is not None
        assert ap_line.credit_amount == Decimal('300.03')

    def test_edit_bill_recreates_je(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='JEV003')
        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        # Create the bill
        client.post('/accounts-payable/create', data={
            'ap_number': 'PBJ-003',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items_payload(
                amount=5000.00, vat_code='', account_id=exp.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
        assert bill is not None, "Bill PBJ-003 not created"
        old_je_id = bill.journal_entry_id
        assert old_je_id is not None

        # Edit the bill (row_version: the edit contract now carries a version token)
        client.post(f'/accounts-payable/{bill.id}/edit', data={
            'ap_number': 'PBJ-003',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'row_version': bill.row_version,
            'line_items': make_line_items_payload(
                amount=6000.00, vat_code='', account_id=exp.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        db_session.expire_all()
        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
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

    def test_edit_bill_subtotal_reflects_new_amount(
            self, client, db_session, accountant_user, main_branch):
        """Regression: ap.subtotal/total_amount must be written from the NEW lines after edit.

        A bulk Query.delete() does not evict the ORM line_items collection.  Without
        db.session.expire(ap, ['line_items']) after the flush, calculate_totals() iterates
        stale old lines and commits the wrong totals — this test catches that.
        """
        login(client)
        vendor = make_vendor(db_session, code='JEV005')
        get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        # Create the bill at 5000
        client.post('/accounts-payable/create', data={
            'ap_number': 'PBJ-005',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test subtotal',
            'line_items': make_line_items_payload(amount=5000.00, vat_code='', account_id=exp.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
        assert bill is not None, "Bill PBJ-005 not created"

        # Edit the bill to 7500
        client.post(f'/accounts-payable/{bill.id}/edit', data={
            'ap_number': 'PBJ-005',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test subtotal',
            'row_version': bill.row_version,
            'line_items': make_line_items_payload(amount=7500.00, vat_code='', account_id=exp.id),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        # expire_all forces a fresh DB read — ensures we are not hitting the ORM cache
        db_session.expire_all()
        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
        assert bill.subtotal == Decimal('7500.00'), (
            f"Expected subtotal 7500, got {bill.subtotal} — stale line_items collection in calculate_totals?")
        assert bill.total_amount == Decimal('7500.00'), (
            f"Expected total_amount 7500, got {bill.total_amount}")
