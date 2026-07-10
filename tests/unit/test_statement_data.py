# tests/unit/test_statement_data.py
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.sales_memos.models import SalesMemo
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
from app.reports.statement_data import build_statement_of_account

pytestmark = [pytest.mark.unit, pytest.mark.reports]

JULY = {'date_from': date(2026, 7, 1), 'date_to': date(2026, 7, 31),
        'label': 'July 2026'}


def _cust(branch):
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    return c


def _si(branch, c, number, d, total, status='posted'):
    si = SalesInvoice(branch_id=branch.id, invoice_number=number, invoice_date=d,
                      due_date=d, customer_id=c.id, customer_name=c.name, notes='',
                      status=status, total_amount=Decimal(total), balance=Decimal(total))
    db.session.add(si); db.session.commit()
    return si


def _debit(branch, c, si, number, d, total):
    m = SalesMemo(memo_type='debit', memo_number=number, memo_date=d,
                  sales_invoice_id=si.id, original_invoice_number=si.invoice_number,
                  branch_id=branch.id, customer_id=c.id, customer_name=c.name,
                  reason='chg', notes='', subtotal=Decimal(total), total_amount=Decimal(total),
                  balance=Decimal(total), amount_paid=Decimal('0.00'),
                  destination='ar', status='posted')
    db.session.add(m); db.session.commit()
    return m


def _credit_ar(branch, c, si, number, d, total):
    m = SalesMemo(memo_type='credit', memo_number=number, memo_date=d,
                  sales_invoice_id=si.id, original_invoice_number=si.invoice_number,
                  branch_id=branch.id, customer_id=c.id, customer_name=c.name,
                  reason='ret', notes='', subtotal=Decimal(total), total_amount=Decimal(total),
                  destination='ar', status='posted')
    db.session.add(m); db.session.commit()
    return m


def _cash_account():
    # CashReceiptVoucher.cash_account_id is NOT NULL on the real model (the brief's
    # helper used None); get-or-create a minimal cash account to satisfy the constraint.
    acct = Account.query.filter_by(code='1001').first()
    if acct is None:
        acct = Account(code='1001', name='Cash on Hand', account_type='Asset',
                       classification='Current Asset', normal_balance='Debit')
        db.session.add(acct); db.session.commit()
    return acct


def _crv_pay(branch, c, number, d, doc, amount):
    crv = CashReceiptVoucher(branch_id=branch.id, crv_number=number, crv_date=d,
                             customer_id=c.id, customer_name=c.name, payment_method='cash',
                             cash_account_id=_cash_account().id, notes='', status='posted')
    line = CRVArLine(line_number=1, invoice_number=doc.invoice_number if hasattr(doc, 'invoice_number') else doc.memo_number,
                     original_balance=Decimal(amount), amount_applied=Decimal(amount))
    if isinstance(doc, SalesInvoice):
        line.invoice_id = doc.id
    else:
        line.sales_memo_id = doc.id
    crv.ar_lines.append(line)
    db.session.add(crv); db.session.commit()
    return crv


def test_opening_balance_from_pre_period_events(db_session, main_branch):
    c = _cust(main_branch)
    _si(main_branch, c, 'SI-0001', date(2026, 6, 10), '12000.00')   # pre-period charge
    _crv_pay(main_branch, c, 'CR-1', date(2026, 6, 20),
             SalesInvoice.query.filter_by(invoice_number='SI-0001').first(), '2000.00')
    result = build_statement_of_account(c.id, main_branch.id, JULY)
    assert result['opening_balance'] == Decimal('10000.00')   # 12000 - 2000, both pre-period
    assert result['rows'] == []


def test_running_balance_threads_through_mixed_events(db_session, main_branch):
    c = _cust(main_branch)
    _si(main_branch, c, 'SI-0001', date(2026, 6, 10), '12000.00')            # opening 12000
    si7 = _si(main_branch, c, 'SI-0007', date(2026, 7, 3), '5600.00')        # +5600
    _debit(main_branch, c, si7, 'DM-0001', date(2026, 7, 10), '560.00')      # +560
    _credit_ar(main_branch, c, si7, 'CM-0002', date(2026, 7, 18), '1120.00') # -1120
    _crv_pay(main_branch, c, 'CR-0044', date(2026, 7, 25), si7, '4000.00')   # -4000
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    assert r['opening_balance'] == Decimal('12000.00')
    bals = [row['running_balance'] for row in r['rows']]
    assert bals == [Decimal('17600.00'), Decimal('18160.00'),
                    Decimal('17040.00'), Decimal('13040.00')]
    assert r['total_charges'] == Decimal('6160.00')
    assert r['total_credits'] == Decimal('5120.00')
    assert r['closing_balance'] == Decimal('13040.00')          # opening + charges - credits


def test_excludes_voided_cancelled_and_non_ar_credit(db_session, main_branch):
    c = _cust(main_branch)
    si = _si(main_branch, c, 'SI-0007', date(2026, 7, 3), '5600.00')
    _si(main_branch, c, 'SI-VOID', date(2026, 7, 4), '9999.00', status='voided')
    # non-AR credit memo (cash refund) must not appear
    m = _credit_ar(main_branch, c, si, 'CM-CASH', date(2026, 7, 5), '500.00')
    m.destination = 'cash_refund'; db.session.commit()
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    numbers = [row['doc_number'] for row in r['rows']]
    assert numbers == ['SI-0007']
    assert r['closing_balance'] == Decimal('5600.00')


def test_empty_activity_opening_equals_closing(db_session, main_branch):
    c = _cust(main_branch)
    _si(main_branch, c, 'SI-OLD', date(2026, 6, 1), '3000.00')
    r = build_statement_of_account(c.id, main_branch.id, JULY)
    assert r['rows'] == []
    assert r['opening_balance'] == Decimal('3000.00')
    assert r['closing_balance'] == Decimal('3000.00')


def test_excludes_other_customer_and_branch(db_session, main_branch, branch_manila):
    target = _cust(main_branch)
    _si(main_branch, target, 'SI-MINE', date(2026, 7, 10), '1000.00')

    # (a) a different customer, same branch, in-period SI -- must not leak in.
    other_cust = Customer(code='C2', name='Other Co', is_active=True)
    db.session.add(other_cust); db.session.commit()
    _si(main_branch, other_cust, 'SI-OTHER-CUST', date(2026, 7, 11), '2000.00')

    # (b) the target customer, but a DIFFERENT branch -- must not leak in.
    _si(branch_manila, target, 'SI-OTHER-BR', date(2026, 7, 12), '3000.00')

    r = build_statement_of_account(target.id, main_branch.id, JULY)
    numbers = [row['doc_number'] for row in r['rows']]
    assert numbers == ['SI-MINE']
    assert r['closing_balance'] == Decimal('1000.00')


def test_same_date_events_ordered_deterministically(db_session, main_branch):
    c = _cust(main_branch)
    si = _si(main_branch, c, 'SI-0001', date(2026, 7, 15), '5000.00')
    _crv_pay(main_branch, c, 'CR-0001', date(2026, 7, 15), si, '2000.00')

    r = build_statement_of_account(c.id, main_branch.id, JULY)
    kinds = [row['kind'] for row in r['rows']]
    assert kinds == ['invoice', 'payment']

    bals = [row['running_balance'] for row in r['rows']]
    opening = r['opening_balance']
    assert bals == [opening + Decimal('5000.00'), opening + Decimal('5000.00') - Decimal('2000.00')]
