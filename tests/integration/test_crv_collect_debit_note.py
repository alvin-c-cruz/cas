"""Phase 2b: the CRV open-items list includes posted debit notes (balance>0), tagged."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
from app.cash_receipts.views import (
    _parse_line_items, _apply_ar_collections, _reverse_ar_collections, CRVLineError,
)
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
        'cash': _acct('10101', 'Cash on Hand', 'Asset', 'Debit'),
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


def _draft_crv(c, main_branch, num='CR-T3-1'):
    cash = Account.query.filter_by(code='10101').first()
    crv = CashReceiptVoucher(
        branch_id=main_branch.id, crv_number=num, crv_date=date(2026, 7, 11),
        customer_id=c.id, customer_name=c.name, payment_method='cash',
        cash_account_id=cash.id, notes='', status='draft')
    db.session.add(crv); db.session.commit()
    return crv


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


# --- T3: parser routes an AR line to either SI or debit note (nullable dual FK) --------

def test_parser_routes_debit_note_line_to_sales_memo(client, db_session, admin_user, main_branch, app):
    c, si, li = _setup(client, admin_user, main_branch)
    memo = _post_debit_note(client, si, li, charge='560')
    crv = _draft_crv(c, main_branch)
    ar = json.dumps([{'invoice_id': memo.id, 'amount_applied': '560', 'type': 'debit_note'}])
    with app.test_request_context('/cash-receipts/create', method='POST',
                                  data={'ar_lines': ar, 'revenue_lines': '[]'}):
        _parse_line_items(crv)
    db.session.commit()
    line = crv.ar_lines[0]
    assert line.sales_memo_id == memo.id      # routed to the debit note
    assert line.invoice_id is None            # exactly-one: SI side left null
    assert line.invoice_number == memo.memo_number
    assert line.original_balance == Decimal('560.00')


def test_parser_si_line_unaffected(client, db_session, admin_user, main_branch, app):
    c, si, li = _setup(client, admin_user, main_branch)
    crv = _draft_crv(c, main_branch)
    ar = json.dumps([{'invoice_id': si.id, 'amount_applied': '1120'}])  # no type -> invoice
    with app.test_request_context('/cash-receipts/create', method='POST',
                                  data={'ar_lines': ar, 'revenue_lines': '[]'}):
        _parse_line_items(crv)
    db.session.commit()
    line = crv.ar_lines[0]
    assert line.invoice_id == si.id
    assert line.sales_memo_id is None


def test_parser_rejects_overcollecting_a_debit_note(client, db_session, admin_user, main_branch, app):
    c, si, li = _setup(client, admin_user, main_branch)
    memo = _post_debit_note(client, si, li, charge='560')  # balance 560
    crv = _draft_crv(c, main_branch)
    ar = json.dumps([{'invoice_id': memo.id, 'amount_applied': '600', 'type': 'debit_note'}])
    with app.test_request_context('/cash-receipts/create', method='POST',
                                  data={'ar_lines': ar, 'revenue_lines': '[]'}):
        with pytest.raises(CRVLineError):
            _parse_line_items(crv)


def test_apply_and_reverse_collect_the_debit_note_balance(client, db_session, admin_user, main_branch):
    c, si, li = _setup(client, admin_user, main_branch)
    memo = _post_debit_note(client, si, li, charge='560')
    crv = _draft_crv(c, main_branch)
    crv.ar_lines.append(CRVArLine(
        line_number=1, sales_memo_id=memo.id, invoice_number=memo.memo_number,
        original_balance=memo.balance, amount_applied=Decimal('560')))
    db.session.commit()

    _apply_ar_collections(crv); db.session.commit()
    memo = db.session.get(SalesMemo, memo.id)
    assert memo.amount_paid == Decimal('560.00')
    assert memo.balance == Decimal('0.00')
    assert memo.status == 'posted'      # balance-only tracking: no status flip for a debit note

    _reverse_ar_collections(crv); db.session.commit()
    memo = db.session.get(SalesMemo, memo.id)
    assert memo.amount_paid == Decimal('0.00')
    assert memo.balance == Decimal('560.00')
    assert memo.status == 'posted'


def test_edit_form_renders_debit_note_ar_line(client, db_session, admin_user, main_branch):
    # The restore block must not emit `invoice_id: None` (broken JS) for a debit-note
    # line — it restores by ref_id/type. GET the draft CRV edit form and assert a clean render.
    c, si, li = _setup(client, admin_user, main_branch)
    memo = _post_debit_note(client, si, li, charge='560')
    crv = _draft_crv(c, main_branch, num='CR-EDIT-1')
    crv.ar_lines.append(CRVArLine(
        line_number=1, sales_memo_id=memo.id, invoice_number=memo.memo_number,
        original_balance=memo.balance, amount_applied=Decimal('560')))
    db.session.commit()
    resp = client.get(f'/cash-receipts/{crv.id}/edit')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'restoreArLine(' in body
    assert memo.memo_number in body
    assert '"type": "debit_note"' in body          # ref carried into restore payload
    assert 'invoice_id: None' not in body           # no broken JS literal

    # Detail view must link a debit-note AR line to the debit note (not /sales-invoices/None).
    detail = client.get(f'/cash-receipts/{crv.id}')
    assert detail.status_code == 200
    dbody = detail.get_data(as_text=True)
    assert f'/debit-notes/{memo.id}' in dbody
    assert 'Debit Note' in dbody


def test_apply_reverse_si_path_still_flips_status(client, db_session, admin_user, main_branch):
    c, si, li = _setup(client, admin_user, main_branch)
    crv = _draft_crv(c, main_branch)
    crv.ar_lines.append(CRVArLine(
        line_number=1, invoice_id=si.id, invoice_number=si.invoice_number,
        original_balance=si.balance, amount_applied=Decimal('1120')))
    db.session.commit()

    _apply_ar_collections(crv); db.session.commit()
    si = db.session.get(SalesInvoice, si.id)
    assert si.balance == Decimal('0.00')
    assert si.status == 'paid'          # invoice still flips status

    _reverse_ar_collections(crv); db.session.commit()
    si = db.session.get(SalesInvoice, si.id)
    assert si.balance == Decimal('1120.00')
    assert si.status == 'posted'
