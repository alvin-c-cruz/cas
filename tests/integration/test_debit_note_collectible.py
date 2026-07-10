"""Phase 2b: a posted debit note gets a collectible balance; CRVArLine is polymorphic."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_vat_categories.models import SalesVATCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


@pytest.fixture(autouse=True)
def _cache_iso(app):
    from app.utils.cache_helpers import clear_module_config_cache
    with app.app_context():
        clear_module_config_cache()
    yield
    with app.app_context():
        clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _acct(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, classification='General', normal_balance=nb)
    db.session.add(a)
    return a


def _setup(client, admin_user, main_branch):
    coa = {
        'ar': _acct('10201', 'Accounts Receivable - Trade', 'Asset', 'Debit'),
        'wt': _acct('10212', 'Creditable Withholding Tax', 'Asset', 'Debit'),
        'outvat': _acct('20401', 'Output VAT', 'Liability', 'Credit'),
        'rev': _acct('40101', 'Sales - Goods', 'Income', 'Credit'),
    }
    db.session.commit()
    vat = SalesVATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                           output_vat_account_id=coa['outvat'].id, is_active=True)
    db.session.add(vat); db.session.commit()
    AppSettings.set_setting('module_enabled:debit_memos', '1')
    from app.utils.cache_helpers import clear_module_config_cache
    db.session.commit(); clear_module_config_cache()
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-1', invoice_date=date(2026, 7, 1),
                      due_date=date(2026, 7, 31), customer_id=c.id, customer_name='Acme', notes='',
                      status='posted', total_amount=Decimal('1120'), balance=Decimal('1120'))
    li = SalesInvoiceItem(line_number=1, description='Widget', amount=Decimal('1120'),
                          vat_category='V12', vat_rate=Decimal('12'), account_id=coa['rev'].id)
    li.calculate_amounts(); si.line_items.append(li); db.session.add(si); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return si, li


def test_crvarline_is_polymorphic():
    from app.cash_receipts.models import CRVArLine
    cols = {c.name: c for c in CRVArLine.__table__.columns}
    assert 'sales_memo_id' in cols            # can reference a debit note
    assert cols['invoice_id'].nullable is True  # invoice_id relaxed to nullable


def test_debit_note_post_sets_collectible_balance(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch)
    client.post('/debit-notes/create', data={
        'sales_invoice_id': si.id, 'memo_date': '2026-07-10', 'reason': 'Undercharge',
        'destination': 'ar',
        'lines': json.dumps([{'sales_invoice_item_id': li.id, 'amount': '560'}]),
    }, follow_redirects=True)
    memo = SalesMemo.query.filter_by(memo_type='debit').first()
    client.post(f'/debit-notes/{memo.id}/post', follow_redirects=True)
    memo = db.session.get(SalesMemo, memo.id)
    assert memo.status == 'posted'
    assert memo.total_amount == Decimal('560.00')
    assert memo.balance == Decimal('560.00')     # full receivable open for collection
    assert memo.amount_paid == Decimal('0.00')
