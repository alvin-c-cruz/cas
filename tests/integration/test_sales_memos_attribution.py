"""BUG-PO-DETAIL-MISSING-ACTOR-ATTRIBUTION ripple: sales_memos/_view_impl computes `created_by`
but detail.html never rendered it."""
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


@pytest.fixture(autouse=True)
def _module_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:credit_memos', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def customer(db_session):
    from app.customers.models import Customer
    c = Customer(code='CMC01', name='Memo Test Customer', is_active=True)
    db_session.add(c); db_session.commit()
    return c


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _make_posted_invoice(db_session, customer, branch, user):
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    inv = SalesInvoice(
        branch_id=branch.id, invoice_number='SI-2026-MEMOTEST', invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14), customer_id=customer.id, customer_name=customer.name,
        notes='', status='posted', subtotal=Decimal('1120.00'), vat_amount=Decimal('120.00'),
        total_before_wt=Decimal('1120.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('1120.00'), amount_paid=Decimal('0.00'), balance=Decimal('1120.00'),
        created_by_id=user.id)
    db_session.add(inv); db_session.flush()
    item = SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='Service',
                            amount=Decimal('1120.00'), vat_rate=Decimal('12.00'))
    db_session.add(item); db_session.commit()
    return inv


def _make_memo(db_session, memo_type, si, customer, branch, user):
    from app.sales_memos.models import SalesMemo, generate_memo_number
    memo = SalesMemo(
        memo_type=memo_type, memo_number=generate_memo_number(memo_type),
        memo_date=date(2026, 7, 16), branch_id=branch.id,
        sales_invoice_id=si.id, original_invoice_number=si.invoice_number,
        customer_id=customer.id, customer_name=customer.name,
        reason='Test reason for memo attribution check', destination='ar',
        notes='', status='draft', created_by_id=user.id)
    db_session.add(memo); db_session.commit()
    return memo


def test_credit_memo_detail_shows_created_by(client, db_session, accountant_user, customer, main_branch):
    _login(client, accountant_user, main_branch)
    si = _make_posted_invoice(db_session, customer, main_branch, accountant_user)
    memo = _make_memo(db_session, 'credit', si, customer, main_branch, accountant_user)
    resp = client.get(f'/credit-memos/{memo.id}')
    assert resp.status_code == 200
    assert b'Created by' in resp.data
    assert b'accountant' in resp.data
