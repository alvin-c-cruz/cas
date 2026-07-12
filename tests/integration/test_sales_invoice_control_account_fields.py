import json
import pytest
from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def test_create_sales_invoice_persists_control_account_override(
        client, db_session, accountant_user, main_branch):
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    ar_override = Account(code='SICF01', name='AR Trade Override', account_type='Asset',
                          normal_balance='Debit', is_active=True)
    revenue_acct = Account(code='SICF02', name='Service Revenue', account_type='Revenue',
                           normal_balance='Credit', is_active=True)
    # The company-default AR control account must resolve too -- _post_invoice_je
    # (Task 4 not yet wired) still calls get_control_account('ar_trade') unconditionally
    # regardless of this invoice's per-transaction override.
    ar_default = Account(code='10201', name='Accounts Receivable - Trade',
                         account_type='Asset', normal_balance='Debit', is_active=True)
    db.session.add_all([ar_override, revenue_acct, ar_default]); db.session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db.session)
    customer = Customer(code='SICFC1', name='Control Field Customer', is_active=True)
    db.session.add(customer); db.session.commit()

    line_items = json.dumps([{
        'description': 'Consulting', 'amount': 1000.00, 'vat_category': '',
        'account_id': revenue_acct.id, 'wt_id': None, 'wt_rate': None,
    }])
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SICF-0001', 'invoice_date': '2026-07-12',
        'due_date': '2026-08-11', 'customer_id': customer.id,
        'payment_terms': 'Net 30', 'notes': 'test',
        'ar_trade_account_id': str(ar_override.id),
        'creditable_wht_account_id': '',
        'line_items': line_items,
    }, follow_redirects=True)
    assert resp.status_code == 200

    invoice = SalesInvoice.query.filter_by(invoice_number='SICF-0001').first()
    assert invoice is not None
    assert invoice.ar_trade_account_id == ar_override.id
    assert invoice.creditable_wht_account_id is None
