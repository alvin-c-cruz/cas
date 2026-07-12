import pytest
from app import db
from app.accounts.models import Account
from app.sales_invoices.models import SalesInvoice
from app.accounts_payable.models import AccountsPayable
from app.customers.models import Customer
from app.vendors.models import Vendor
from datetime import date


def _account(db_session, code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
    db_session.add(a); db_session.commit()
    return a


def test_sales_invoice_control_account_columns(db_session, main_branch):
    ar = _account(db_session, 'CAF001', 'AR Trade Custom', 'Asset', 'Debit')
    wt = _account(db_session, 'CAF002', 'Creditable WHT Custom', 'Asset', 'Debit')
    customer = Customer(code='CAFC01', name='Field Test Customer', is_active=True)
    db_session.add(customer); db_session.commit()
    invoice = SalesInvoice(
        branch_id=main_branch.id, invoice_number='CAF-SI-0001',
        invoice_date=date.today(), due_date=date.today(),
        customer_id=customer.id, customer_name=customer.name,
        status='draft', ar_trade_account_id=ar.id, creditable_wht_account_id=wt.id,
    )
    db.session.add(invoice)
    db.session.commit()
    fetched = db.session.get(SalesInvoice, invoice.id)
    assert fetched.ar_trade_account.code == 'CAF001'
    assert fetched.creditable_wht_account.code == 'CAF002'


def test_accounts_payable_control_account_columns(db_session, main_branch):
    ap_acct = _account(db_session, 'CAF003', 'AP Trade Custom', 'Liability', 'Credit')
    wt_acct = _account(db_session, 'CAF004', 'WHT Payable Custom', 'Liability', 'Credit')
    vendor = Vendor(code='CAFV01', name='Field Test Vendor', is_active=True)
    db.session.add(vendor); db.session.commit()
    ap = AccountsPayable(
        branch_id=main_branch.id, ap_number='CAF-AP-0001',
        ap_date=date.today(), due_date=date.today(),
        payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id, vendor_name=vendor.name,
        status='draft', ap_trade_account_id=ap_acct.id, wht_payable_account_id=wt_acct.id,
    )
    db.session.add(ap)
    db.session.commit()
    fetched = db.session.get(AccountsPayable, ap.id)
    assert fetched.ap_trade_account.code == 'CAF003'
    assert fetched.wht_payable_account.code == 'CAF004'
