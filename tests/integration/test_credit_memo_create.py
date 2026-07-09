"""Credit Memo create form + grid + line snapshot/calc."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.accounts.models import Account
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _enable(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:credit_memos', '1')
    db_session.commit(); clear_module_config_cache()


def _posted_si(db_session, branch, amount='1120', vat_rate='12'):
    c = Customer(code='CMC1', name='Acme Corp', is_active=True)
    a = Account(code='40101', name='Sales - Goods', account_type='Income',
                classification='General', normal_balance='Credit')
    db.session.add_all([c, a]); db.session.commit()
    si = SalesInvoice(branch_id=branch.id, invoice_number='SI-CM-1',
                      invoice_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
                      customer_id=c.id, customer_name=c.name, notes='', status='posted',
                      total_amount=Decimal(amount), balance=Decimal(amount))
    li = SalesInvoiceItem(line_number=1, description='Widget', amount=Decimal(amount),
                          vat_category='V12', vat_rate=Decimal(vat_rate), account_id=a.id)
    li.calculate_amounts()
    si.line_items.append(li)
    db.session.add(si); db.session.commit()
    return si


def _setup(client, db_session, admin_user, main_branch):
    _enable(db_session); _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return _posted_si(db_session, main_branch)


def test_create_form_renders_lines_field_once(client, db_session, admin_user, main_branch):
    _setup(client, db_session, admin_user, main_branch)
    resp = client.get('/credit-memos/create')
    assert resp.status_code == 200
    assert resp.data.count(b'name="lines"') == 1


def test_si_lines_endpoint_returns_invoice_lines(client, db_session, admin_user, main_branch):
    si = _setup(client, db_session, admin_user, main_branch)
    resp = client.get(f'/credit-memos/si-lines/{si.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['customer_name'] == 'Acme Corp'
    assert len(data['lines']) == 1
    assert data['lines'][0]['creditable'] == 1120.0


def test_create_persists_memo_with_snapshot_and_calc(client, db_session, admin_user, main_branch):
    si = _setup(client, db_session, admin_user, main_branch)
    soi = si.line_items[0]
    resp = client.post('/credit-memos/create', data={
        'sales_invoice_id': si.id, 'memo_date': '2026-07-10', 'reason': 'Returned goods',
        'destination': 'ar',
        'lines': json.dumps([{'sales_invoice_item_id': soi.id, 'amount': '560'}]),
    }, follow_redirects=True)
    assert resp.status_code == 200
    memo = SalesMemo.query.filter_by(memo_type='credit').first()
    assert memo is not None and memo.status == 'draft'
    assert memo.original_invoice_number == 'SI-CM-1'
    assert memo.customer_name == 'Acme Corp'
    assert memo.memo_number.startswith('CM-')
    assert len(memo.line_items) == 1
    line = memo.line_items[0]
    assert line.sales_invoice_item_id == soi.id
    assert line.account_id == soi.account_id        # snapshot from SI line
    assert line.vat_category == 'V12'               # snapshot
    assert line.amount == Decimal('560.00')
    assert line.vat_amount == Decimal('60.00')      # 560 - 560/1.12
    assert memo.subtotal == Decimal('560.00')
    assert memo.total_amount == Decimal('560.00')
    from app.audit.models import AuditLog
    assert AuditLog.query.filter_by(module='sales_memos', action='create').first() is not None


def test_create_rejects_over_credit(client, db_session, admin_user, main_branch):
    si = _setup(client, db_session, admin_user, main_branch)
    soi = si.line_items[0]
    client.post('/credit-memos/create', data={
        'sales_invoice_id': si.id, 'memo_date': '2026-07-10', 'reason': 'Over credit',
        'destination': 'ar',
        'lines': json.dumps([{'sales_invoice_item_id': soi.id, 'amount': '2000'}]),
    }, follow_redirects=True)
    assert SalesMemo.query.filter_by(memo_type='credit').first() is None
