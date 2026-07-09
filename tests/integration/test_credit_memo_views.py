"""Credit Memo register (list), detail view, and printable memo."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo, SalesMemoItem

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


@pytest.fixture(autouse=True)
def _module_cache_isolation():
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _setup(client, admin_user, main_branch, status='draft'):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:credit_memos', '1')
    db.session.commit(); clear_module_config_cache()
    c = Customer(code='C1', name='Acme', is_active=True)
    a = Account(code='40101', name='Sales - Goods', account_type='Income',
                classification='General', normal_balance='Credit')
    db.session.add_all([c, a]); db.session.commit()
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-1',
                      invoice_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
                      customer_id=c.id, customer_name='Acme', notes='', status='posted',
                      total_amount=Decimal('1120'), balance=Decimal('1120'))
    li = SalesInvoiceItem(line_number=1, description='Widget', amount=Decimal('1120'),
                          vat_category='V12', vat_rate=Decimal('12'), account_id=a.id)
    li.calculate_amounts(); si.line_items.append(li); db.session.add(si); db.session.commit()
    memo = SalesMemo(memo_type='credit', memo_number='CM-2026-07-0001',
                     memo_date=date(2026, 7, 10), branch_id=main_branch.id,
                     sales_invoice_id=si.id, original_invoice_number='SI-1', customer_id=c.id,
                     customer_name='Acme', reason='Returned goods', destination='ar', status=status)
    ml = SalesMemoItem(line_number=1, sales_invoice_item_id=li.id, amount=Decimal('560'),
                       vat_category='V12', vat_rate=Decimal('12'), account_id=a.id)
    ml.calculate_amounts(); memo.line_items.append(ml); memo.calculate_totals()
    db.session.add(memo); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return memo.id


def test_list_shows_branch_credit_memos(client, db_session, admin_user, main_branch):
    _setup(client, admin_user, main_branch)
    resp = client.get('/credit-memos')
    assert resp.status_code == 200
    assert b'CM-2026-07-0001' in resp.data
    assert b'+ Enter Credit Memo' in resp.data


def test_detail_renders_post_and_void_for_draft(client, db_session, admin_user, main_branch):
    mid = _setup(client, admin_user, main_branch, status='draft')
    resp = client.get(f'/credit-memos/{mid}')
    assert resp.status_code == 200
    assert f'/credit-memos/{mid}/post'.encode() in resp.data      # Post button present
    assert b'Void Credit Memo' in resp.data


def test_detail_hides_post_button_when_posted(client, db_session, admin_user, main_branch):
    mid = _setup(client, admin_user, main_branch, status='posted')
    resp = client.get(f'/credit-memos/{mid}')
    assert resp.status_code == 200
    assert f'/credit-memos/{mid}/post'.encode() not in resp.data   # no Post once posted
    assert b'Void Credit Memo' in resp.data                        # void still offered


def test_print_renders(client, db_session, admin_user, main_branch):
    mid = _setup(client, admin_user, main_branch)
    resp = client.get(f'/credit-memos/{mid}/print')
    assert resp.status_code == 200
    assert b'CREDIT MEMO' in resp.data
    assert b'CM-2026-07-0001' in resp.data
