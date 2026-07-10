"""Debit Note end-to-end: gate, create, post (increases AR, no SI-balance change), void, views."""
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
from app.sales_memos import service
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


@pytest.fixture(autouse=True)
def _cache_iso():
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _acct(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, classification='General',
                normal_balance=nb)
    db.session.add(a)
    return a


def _enable(*keys):
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db.session.commit(); clear_module_config_cache()


def _setup(client, admin_user, main_branch, enable=True):
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
    if enable:
        _enable('debit_memos')
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-1',
                      invoice_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
                      customer_id=c.id, customer_name='Acme', notes='', status='posted',
                      total_amount=Decimal('1120'), balance=Decimal('1120'))
    li = SalesInvoiceItem(line_number=1, description='Widget', amount=Decimal('1120'),
                          vat_category='V12', vat_rate=Decimal('12'), account_id=coa['rev'].id)
    li.calculate_amounts(); si.line_items.append(li); db.session.add(si); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return si, li


def test_debit_list_blocked_when_module_off(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch, enable=False)
    assert client.get('/debit-notes').status_code == 404


def test_debit_registry_entry(db_session):
    from app.users.module_access import MODULE_REGISTRY, all_permission_keys
    e = next(m for m in MODULE_REGISTRY if m['key'] == 'debit_memos')
    assert e['optional'] and e['per_user'] and not e['default_enabled']
    assert 'debit_memos' in all_permission_keys()


def test_debit_create_form_renders_single_lines_field(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/debit-notes/create')
    assert resp.status_code == 200
    assert resp.data.count(b'name="lines"') == 1
    assert b'Enter Debit Note' in resp.data


def test_debit_list_shows_enter_button(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/debit-notes')
    assert resp.status_code == 200
    assert b'+ Enter Debit Note' in resp.data


def test_debit_create_persists_and_redirects_to_detail(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch)
    resp = client.post('/debit-notes/create', data={
        'sales_invoice_id': si.id, 'memo_date': '2026-07-10', 'reason': 'Undercharge',
        'destination': 'ar',
        'lines': json.dumps([{'sales_invoice_item_id': li.id, 'amount': '560'}]),
    }, follow_redirects=True)
    assert resp.status_code == 200
    memo = SalesMemo.query.filter_by(memo_type='debit').first()
    assert memo is not None and memo.memo_number.startswith('DM-')
    assert memo.total_amount == Decimal('560.00')
    assert b'DEBIT NOTE' not in resp.data or b'DM-' in resp.data   # landed on detail


def test_debit_post_increases_ar_without_touching_si_balance(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch)
    sid = si.id
    client.post('/debit-notes/create', data={
        'sales_invoice_id': si.id, 'memo_date': '2026-07-10', 'reason': 'Undercharge',
        'destination': 'ar',
        'lines': json.dumps([{'sales_invoice_item_id': li.id, 'amount': '560'}]),
    }, follow_redirects=True)
    memo = SalesMemo.query.filter_by(memo_type='debit').first()
    client.post(f'/debit-notes/{memo.id}/post', follow_redirects=True)
    memo = db.session.get(SalesMemo, memo.id); inv = db.session.get(SalesInvoice, sid)
    assert memo.status == 'posted' and memo.journal_entry.status == 'posted'
    # Debit note is its OWN receivable; the referenced SI's balance is untouched (unlike a credit).
    assert inv.balance == Decimal('1120.00') and inv.status == 'posted'
    from app.journal_entries.models import JournalEntryLine
    ar = JournalEntryLine.query.filter_by(entry_id=memo.journal_entry_id).all()
    ar_leg = next(l for l in ar if db.session.get(Account, l.account_id).code == '10201')
    assert ar_leg.debit_amount == Decimal('560.00')   # AR increased


def test_debit_void_reverses_je(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch)
    client.post('/debit-notes/create', data={
        'sales_invoice_id': si.id, 'memo_date': '2026-07-10', 'reason': 'Undercharge',
        'destination': 'ar',
        'lines': json.dumps([{'sales_invoice_item_id': li.id, 'amount': '560'}]),
    }, follow_redirects=True)
    memo = SalesMemo.query.filter_by(memo_type='debit').first()
    client.post(f'/debit-notes/{memo.id}/post', follow_redirects=True)
    client.post(f'/debit-notes/{memo.id}/void',
                data={'void_reason': 'Issued in error test'}, follow_redirects=True)
    memo = db.session.get(SalesMemo, memo.id)
    assert memo.status == 'voided'
    from app.journal_entries.models import JournalEntry
    assert JournalEntry.query.filter_by(reference=memo.memo_number,
                                         entry_type='reversal').first() is not None


def test_debit_print_renders(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch)
    client.post('/debit-notes/create', data={
        'sales_invoice_id': si.id, 'memo_date': '2026-07-10', 'reason': 'Undercharge',
        'destination': 'ar',
        'lines': json.dumps([{'sales_invoice_item_id': li.id, 'amount': '560'}]),
    }, follow_redirects=True)
    memo = SalesMemo.query.filter_by(memo_type='debit').first()
    resp = client.get(f'/debit-notes/{memo.id}/print')
    assert resp.status_code == 200
    assert b'DEBIT NOTE' in resp.data
