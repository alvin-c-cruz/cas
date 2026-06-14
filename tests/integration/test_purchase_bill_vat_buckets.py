"""Per-category input-VAT buckets in purchase JEs (B-014)."""
import json
import pytest
from decimal import Decimal
from datetime import date

from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill
from app.journal_entries.models import JournalEntry
pytestmark = [pytest.mark.purchase_bills, pytest.mark.integration]



def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def setup_world(db_session):
    accts = {}
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Debit'),
        ('10503', 'Input VAT - Services', 'Asset', 'Debit'),
        ('69903', 'Bucket Test Expense', 'Expense', 'Debit'),
    ]:
        a = Account(code=code, name=name, account_type=typ,
                    normal_balance=bal, is_active=True)
        db_session.add(a)
    db_session.commit()
    for code in ['20101', '20301', '10502', '10503', '69903']:
        accts[code] = Account.query.filter_by(code=code).first()

    dg = VATCategory(code='V12DG', name='Input Tax Domestic Goods', rate=12.00,
                     is_active=True, input_vat_account_id=accts['10502'].id)
    sv = VATCategory(code='V12SV', name='Input Tax Services', rate=12.00,
                     is_active=True, input_vat_account_id=accts['10503'].id)
    un = VATCategory(code='V12UN', name='Unmapped 12%', rate=12.00, is_active=True)
    db_session.add_all([dg, sv, un])
    vendor = Vendor(code='BKT01', name='Bucket Vendor',
                    check_payee_name='Bucket Vendor', is_active=True)
    db_session.add(vendor)
    db_session.commit()
    accts['vendor'] = vendor
    return accts


def post_bill(client, vendor, lines, number='AP-BKT-0001',
              vat_override='0', vat_override_value='0'):
    return client.post('/purchase-bills/create', data={
        'bill_number': number,
        'bill_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'vendor_id': vendor.id, 'payment_terms': 'Net 30',
        'notes': 'Test particulars',
        'line_items': json.dumps(lines),
        'vat_override': vat_override, 'vat_override_value': vat_override_value,
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


def je_lines_by_code(db_session, number):
    """Return (net-amount-by-account-code dict, JournalEntry) for a bill."""
    bill = PurchaseBill.query.filter_by(bill_number=number).first()
    assert bill is not None, f'Bill {number} not created'
    je = db_session.get(JournalEntry, bill.journal_entry_id)
    out = {}
    for l in je.lines.all():
        code = l.account.code
        out.setdefault(code, Decimal('0.00'))
        out[code] += l.debit_amount - l.credit_amount
    return out, je


class TestVatBuckets:
    def test_two_categories_two_input_vat_lines(self, client, db_session,
                                                admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ])
        sums, je = je_lines_by_code(db_session, 'AP-BKT-0001')
        assert sums['10502'] == Decimal('240.00')
        assert sums['10503'] == Decimal('60.00')
        assert je.is_balanced

    def test_override_difference_lands_on_largest_bucket(self, client, db_session,
                                                         admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        # computed VAT: 240 + 60 = 300; override to 301 -> +1 on the 10502 bucket
        post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0002', vat_override='1', vat_override_value='301')
        sums, je = je_lines_by_code(db_session, 'AP-BKT-0002')
        assert sums['10502'] == Decimal('241.00')
        assert sums['10503'] == Decimal('60.00')
        assert je.is_balanced

    def test_unmapped_vat_bearing_category_blocks_save(self, client, db_session,
                                                       admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = post_bill(client, w['vendor'], [
            {'description': 'x', 'amount': 1120.0, 'vat_category': 'V12UN',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0003')
        html = resp.data.decode('utf-8')
        assert 'has no Input Tax account configured' in html
        assert PurchaseBill.query.filter_by(bill_number='AP-BKT-0003').first() is None

    def test_override_zero_books_no_input_vat_lines(self, client, db_session,
                                                    admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        # Whole-bill VAT override of 0 on VAT-bearing lines: no input VAT
        # to book; the JE's residual absorber handles the difference.
        post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0004', vat_override='1', vat_override_value='0')
        sums, je = je_lines_by_code(db_session, 'AP-BKT-0004')
        assert '10502' not in sums
        assert '10503' not in sums
        assert je.is_balanced

    def test_override_far_below_computed_blocks_save(self, client, db_session,
                                                     admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        # computed VAT: 240 + 60 = 300; override 50 -> largest 240 - 250 = -10
        resp = post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0005', vat_override='1', vat_override_value='50')
        html = resp.data.decode('utf-8')
        assert 'too far below the computed VAT' in html
        assert PurchaseBill.query.filter_by(bill_number='AP-BKT-0005').first() is None


class TestReversalMirrorsJE:
    def test_cancel_reverses_bucketed_lines(self, client, db_session,
                                            admin_user, main_branch):
        w = setup_world(db_session)
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
            {'description': 'services', 'amount': 560.0, 'vat_category': 'V12SV',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0006')
        bill = PurchaseBill.query.filter_by(bill_number='AP-BKT-0006').first()
        assert bill is not None
        bill.vendor_invoice_number = 'SI-1'
        bill.vendor_invoice_date = date(2026, 6, 12)
        db_session.commit()
        client.post(f'/purchase-bills/{bill.id}/post', follow_redirects=True)
        client.post(f'/purchase-bills/{bill.id}/cancel', data={
            'cancel_reason': 'bucket reversal test reason',
            'reversal_date': '2026-06-12',
        }, follow_redirects=True)

        bill = PurchaseBill.query.filter_by(bill_number='AP-BKT-0006').first()
        assert bill.status == 'cancelled'
        reversal = (JournalEntry.query
                    .filter(JournalEntry.reference.like('%AP-BKT-0006%'),
                            JournalEntry.entry_type == 'reversal').first())
        assert reversal is not None
        assert reversal.is_balanced
        sums = {}
        for l in reversal.lines.all():
            sums.setdefault(l.account.code, Decimal('0.00'))
            sums[l.account.code] += l.credit_amount - l.debit_amount
        # reversal CREDITS what the original debited
        assert sums['10502'] == Decimal('240.00')
        assert sums['10503'] == Decimal('60.00')
        # AP was credited originally -> the reversal debits it, so credit - debit < 0
        assert sums['20101'] < 0

    def test_cancel_without_stored_je_raises_clear_error(self, client, db_session,
                                                         admin_user, main_branch):
        """A posted bill whose JE link is gone must fail loudly, not book a
        wrong reversal rebuilt from totals."""
        import pytest as _pytest
        from app.purchase_bills.views import _create_reversal_je

        w = setup_world(db_session)
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        post_bill(client, w['vendor'], [
            {'description': 'goods', 'amount': 1120.0, 'vat_category': 'V12DG',
             'account_id': w['69903'].id, 'wt_id': None, 'wt_rate': None},
        ], number='AP-BKT-0007')
        bill = PurchaseBill.query.filter_by(bill_number='AP-BKT-0007').first()
        bill.journal_entry_id = None
        db_session.commit()
        with _pytest.raises(ValueError, match='no stored journal entry'):
            _create_reversal_je(bill, date(2026, 6, 12), admin_user.id,
                                label='Cancel')
