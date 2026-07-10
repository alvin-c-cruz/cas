"""Phase 2b: the CRV open-items list includes posted debit notes (balance>0), tagged."""
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

pytestmark = [pytest.mark.integration, pytest.mark.cash_receipts]


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
    return c, si, li


def _post_debit_note(client, si, li, charge='560'):
    client.post('/debit-notes/create', data={
        'sales_invoice_id': si.id, 'memo_date': '2026-07-10', 'reason': 'Undercharge',
        'destination': 'ar',
        'lines': json.dumps([{'sales_invoice_item_id': li.id, 'amount': charge}]),
    }, follow_redirects=True)
    memo = SalesMemo.query.filter_by(memo_type='debit').first()
    client.post(f'/debit-notes/{memo.id}/post', follow_redirects=True)
    return db.session.get(SalesMemo, memo.id)


def test_open_invoices_includes_posted_debit_notes_tagged(client, db_session, admin_user, main_branch):
    c, si, li = _setup(client, admin_user, main_branch)
    memo = _post_debit_note(client, si, li, charge='560')
    resp = client.get(f'/cash-receipts/open-invoices?customer_id={c.id}')
    assert resp.status_code == 200
    by_num = {x['invoice_number']: x for x in resp.get_json()}
    assert by_num['SI-1']['type'] == 'invoice'
    assert memo.memo_number in by_num
    dn = by_num[memo.memo_number]
    assert dn['type'] == 'debit_note'
    assert dn['id'] == memo.id
    assert dn['balance'] == 560.0
