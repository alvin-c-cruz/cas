"""Per-category input-VAT buckets in purchase JEs (B-014)."""
import json
from decimal import Decimal
from datetime import date

from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill
from app.journal_entries.models import JournalEntry


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
        'line_items': json.dumps(lines),
        'vat_override': vat_override, 'vat_override_value': vat_override_value,
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


def je_lines_by_code(db_session, number):
    bill = PurchaseBill.query.filter_by(bill_number=number).first()
    assert bill is not None, f'Bill {number} not created'
    je = db_session.get(JournalEntry, bill.journal_entry_id)
    out = {}
    for l in je.lines.all():
        code = l.account.code
        out.setdefault(code, Decimal('0.00'))
        out[code] += l.debit_amount - l.credit_amount
    return out


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
        sums = je_lines_by_code(db_session, 'AP-BKT-0001')
        assert sums['10502'] == Decimal('240.00')
        assert sums['10503'] == Decimal('60.00')

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
        sums = je_lines_by_code(db_session, 'AP-BKT-0002')
        assert sums['10502'] == Decimal('241.00')
        assert sums['10503'] == Decimal('60.00')

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
