"""Integration tests — pencil-click VAT/WHT override (±1 cent adjustment)."""
import json
import pytest
from decimal import Decimal
from datetime import date
from app.accounts_payable.models import AccountsPayable
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax
pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]




def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def get_or_create_account(db_session, code, name, acct_type):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=acct_type,
                    normal_balance='debit' if acct_type == 'Expense' else 'credit',
                    is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def make_line_items(amount, vat_code='', account_id=None, wt_id=None, wt_rate=None):
    return json.dumps([{
        'description': 'Override test line',
        'amount': amount,
        'vat_category': vat_code,
        'account_id': account_id,
        'wt_id': wt_id,
        'wt_rate': wt_rate,
    }])


class TestBillPencilOverride:
    """The pencil icon in the AP Voucher Summary panel lets users manually fix
    computed VAT or WHT amounts by ±1 cent to match the supplier's invoice exactly."""

    def _fixtures(self, db_session):
        ap = get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
        vat_acct = get_or_create_account(db_session, '10501', 'Input VAT - Current', 'Asset')
        wt_acct = get_or_create_account(db_session, '20301', 'WHT Payable - Expanded', 'Liability')
        exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

        vat_cat = VATCategory(code='OVR12', name='VAT 12% Override Test',
                              rate=Decimal('12'), is_active=True,
                              input_vat_account_id=vat_acct.id)
        db_session.add(vat_cat)

        wt = WithholdingTax(code='OVR01', name='EWT 1% Override Test',
                            rate=Decimal('1'), is_active=True)
        db_session.add(wt)

        vendor = Vendor(code='OVRV01', name='Override Test Vendor',
                        check_payee_name='Override Test Vendor',
                        is_active=True, payment_terms='Net 30')
        db_session.add(vendor)
        db_session.commit()

        return {'ap': ap, 'vat_acct': vat_acct, 'wt_acct': wt_acct,
                'exp': exp, 'vat_cat': vat_cat, 'wt': wt, 'vendor': vendor}

    def test_vat_override_stores_custom_amount(
            self, client, db_session, accountant_user, main_branch):
        """VAT override flag and custom amount are persisted on the bill.

        ₱11,200 incl. 12% VAT → computed VAT = ₱1,200.00.
        Supplier's invoice shows ₱1,200.01 (+1 cent). Override should win.
        """
        login(client)
        fx = self._fixtures(db_session)

        client.post('/accounts-payable/create', data={
            'ap_number': 'OVR-001',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': fx['vendor'].id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items(
                11200.00, vat_code='OVR12', account_id=fx['exp'].id),
            'vat_override': '1',
            'vat_override_value': '1200.01',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        bill = AccountsPayable.query.filter_by(ap_number='OVR-001').first()
        assert bill is not None
        assert bill.vat_override is True
        assert bill.vat_amount == Decimal('1200.01')

    def test_vat_override_minus_one_cent(
            self, client, db_session, accountant_user, main_branch):
        """VAT override with -1 cent is also valid."""
        login(client)
        fx = self._fixtures(db_session)

        client.post('/accounts-payable/create', data={
            'ap_number': 'OVR-002',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': fx['vendor'].id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items(
                11200.00, vat_code='OVR12', account_id=fx['exp'].id),
            'vat_override': '1',
            'vat_override_value': '1199.99',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        bill = AccountsPayable.query.filter_by(ap_number='OVR-002').first()
        assert bill is not None
        assert bill.vat_override is True
        assert bill.vat_amount == Decimal('1199.99')

    def test_vat_override_je_uses_custom_amount_and_balances(
            self, client, db_session, accountant_user, main_branch):
        """JE Input VAT debit reflects the overridden amount, and debits == credits."""
        login(client)
        fx = self._fixtures(db_session)

        client.post('/accounts-payable/create', data={
            'ap_number': 'OVR-003',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': fx['vendor'].id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items(
                11200.00, vat_code='OVR12', account_id=fx['exp'].id),
            'vat_override': '1',
            'vat_override_value': '1200.01',
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        bill = AccountsPayable.query.filter_by(ap_number='OVR-003').first()
        assert bill is not None
        je = db_session.get(JournalEntry, bill.journal_entry_id)
        lines = JournalEntryLine.query.filter_by(entry_id=je.id).all()

        vat_line = next((l for l in lines if l.account_id == fx['vat_acct'].id), None)
        assert vat_line is not None, "No Input VAT line in JE"
        assert vat_line.debit_amount == Decimal('1200.01')

        total_dr = sum(l.debit_amount for l in lines)
        total_cr = sum(l.credit_amount for l in lines)
        assert total_dr == total_cr, f"JE unbalanced: Dr {total_dr} ≠ Cr {total_cr}"

    def test_wt_override_stores_custom_amount(
            self, client, db_session, accountant_user, main_branch):
        """WHT override flag and custom amount are persisted on the bill.

        ₱10,000 no-VAT, 1% WHT → computed WHT = ₱100.00.
        Override to ₱100.01 (+1 cent).
        """
        login(client)
        fx = self._fixtures(db_session)

        client.post('/accounts-payable/create', data={
            'ap_number': 'OVR-004',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': fx['vendor'].id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items(
                10000.00, vat_code='', account_id=fx['exp'].id,
                wt_id=fx['wt'].id, wt_rate=float(fx['wt'].rate)),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '1',
            'wt_override_value': '100.01',
        }, follow_redirects=True)

        bill = AccountsPayable.query.filter_by(ap_number='OVR-004').first()
        assert bill is not None
        assert bill.wt_override is True
        assert bill.withholding_tax_amount == Decimal('100.01')

    def test_wt_override_je_uses_custom_amount_and_balances(
            self, client, db_session, accountant_user, main_branch):
        """JE WHT Payable credit reflects the overridden amount, and debits == credits."""
        login(client)
        fx = self._fixtures(db_session)

        client.post('/accounts-payable/create', data={
            'ap_number': 'OVR-005',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': fx['vendor'].id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items(
                10000.00, vat_code='', account_id=fx['exp'].id,
                wt_id=fx['wt'].id, wt_rate=float(fx['wt'].rate)),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '1',
            'wt_override_value': '99.99',
        }, follow_redirects=True)

        bill = AccountsPayable.query.filter_by(ap_number='OVR-005').first()
        assert bill is not None
        je = db_session.get(JournalEntry, bill.journal_entry_id)
        lines = JournalEntryLine.query.filter_by(entry_id=je.id).all()

        wt_line = next((l for l in lines if l.account_id == fx['wt_acct'].id), None)
        assert wt_line is not None, "No WHT Payable line in JE"
        assert wt_line.credit_amount == Decimal('99.99')

        total_dr = sum(l.debit_amount for l in lines)
        total_cr = sum(l.credit_amount for l in lines)
        assert total_dr == total_cr, f"JE unbalanced: Dr {total_dr} ≠ Cr {total_cr}"

    def test_both_overrides_together(
            self, client, db_session, accountant_user, main_branch):
        """VAT and WHT can both be overridden in the same save; JE stays balanced."""
        login(client)
        fx = self._fixtures(db_session)

        # ₱11,200 incl. 12% VAT + 1% WHT on base
        client.post('/accounts-payable/create', data={
            'ap_number': 'OVR-006',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': fx['vendor'].id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items(
                11200.00, vat_code='OVR12', account_id=fx['exp'].id,
                wt_id=fx['wt'].id, wt_rate=float(fx['wt'].rate)),
            'vat_override': '1',
            'vat_override_value': '1200.01',
            'wt_override': '1',
            'wt_override_value': '99.99',
        }, follow_redirects=True)

        bill = AccountsPayable.query.filter_by(ap_number='OVR-006').first()
        assert bill is not None
        assert bill.vat_override is True
        assert bill.vat_amount == Decimal('1200.01')
        assert bill.wt_override is True
        assert bill.withholding_tax_amount == Decimal('99.99')

        je = db_session.get(JournalEntry, bill.journal_entry_id)
        lines = JournalEntryLine.query.filter_by(entry_id=je.id).all()
        total_dr = sum(l.debit_amount for l in lines)
        total_cr = sum(l.credit_amount for l in lines)
        assert total_dr == total_cr, f"JE unbalanced with both overrides: Dr {total_dr} ≠ Cr {total_cr}"

    def test_vat_override_out_of_range_rejected(
            self, client, db_session, accountant_user, main_branch):
        """Override value exceeding the bill subtotal is rejected — no bill saved."""
        login(client)
        fx = self._fixtures(db_session)

        client.post('/accounts-payable/create', data={
            'ap_number': 'OVR-BAD',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': fx['vendor'].id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items(
                11200.00, vat_code='OVR12', account_id=fx['exp'].id),
            'vat_override': '1',
            'vat_override_value': '99999.99',  # exceeds subtotal (11200)
            'wt_override': '0',
            'wt_override_value': '0',
        }, follow_redirects=True)

        bill = AccountsPayable.query.filter_by(ap_number='OVR-BAD').first()
        assert bill is None  # rejected, not persisted

    def test_wt_override_out_of_range_rejected(
            self, client, db_session, accountant_user, main_branch):
        """WHT override value exceeding the bill subtotal is rejected — no bill saved."""
        login(client)
        fx = self._fixtures(db_session)

        client.post('/accounts-payable/create', data={
            'ap_number': 'OVR-BAD2',
            'ap_date': date.today().isoformat(),
            'due_date': date.today().isoformat(),
            'vendor_id': fx['vendor'].id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': make_line_items(
                10000.00, vat_code='', account_id=fx['exp'].id,
                wt_id=fx['wt'].id, wt_rate=float(fx['wt'].rate)),
            'vat_override': '0',
            'vat_override_value': '0',
            'wt_override': '1',
            'wt_override_value': '99999.99',  # exceeds subtotal (10000)
        }, follow_redirects=True)

        bill = AccountsPayable.query.filter_by(ap_number='OVR-BAD2').first()
        assert bill is None
