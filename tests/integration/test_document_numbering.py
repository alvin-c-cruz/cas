"""SI invoice_number and CR crv_number use a plain continuous 5-digit sequence.

Format: 00001, 00002, ... — NO prefix, NO year/month, never resets. Each document
type keeps its own independent running sequence. Legacy prefixed numbers (e.g.
'SI-2026-0030') are ignored when computing the next number.
"""
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.sales_invoices.views import generate_invoice_number
from app.cash_receipts.models import CashReceiptVoucher
from app.cash_receipts.views import generate_crv_number

pytestmark = [pytest.mark.integration]


def _customer(db_session):
    c = Customer(code='C-NUM', name='Numbering Test Co', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _account(db_session):
    from app.accounts.models import Account
    a = Account(code='10100', name='Cash on Hand (num test)', account_type='Asset',
                normal_balance='Debit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


def _si(db_session, number, customer, branch_id):
    inv = SalesInvoice(
        branch_id=branch_id, invoice_number=number,
        invoice_date=date(2026, 6, 1), due_date=date(2026, 6, 30),
        customer_id=customer.id, customer_name=customer.name, notes='', status='draft',
        amount_paid=Decimal('0'), balance=Decimal('0'), total_amount=Decimal('0'),
        subtotal=Decimal('0'), vat_amount=Decimal('0'), withholding_tax_amount=Decimal('0'))
    db_session.add(inv)
    db_session.commit()
    return inv


def _crv(db_session, number, customer, cash_acct, branch_id):
    crv = CashReceiptVoucher(
        branch_id=branch_id, crv_number=number, crv_date=date(2026, 6, 1),
        customer_id=customer.id, customer_name=customer.name,
        cash_account_id=cash_acct.id, notes='', status='draft')
    db_session.add(crv)
    db_session.commit()
    return crv


class TestInvoiceNumber:
    def test_starts_at_00001(self, db_session, main_branch):
        assert generate_invoice_number() == '00001'

    def test_increments_continuously(self, db_session, main_branch):
        c = _customer(db_session)
        _si(db_session, '00001', c, main_branch.id)
        assert generate_invoice_number() == '00002'

    def test_ignores_legacy_prefixed_numbers(self, db_session, main_branch):
        c = _customer(db_session)
        _si(db_session, 'SI-2026-0030', c, main_branch.id)
        assert generate_invoice_number() == '00001'

    def test_is_five_digit_no_prefix(self, db_session, main_branch):
        n = generate_invoice_number()
        assert n.isdigit() and len(n) == 5


class TestCrvNumber:
    def test_starts_at_00001(self, db_session, main_branch):
        assert generate_crv_number() == '00001'

    def test_increments_continuously(self, db_session, main_branch):
        c = _customer(db_session)
        a = _account(db_session)
        _crv(db_session, '00001', c, a, main_branch.id)
        assert generate_crv_number() == '00002'

    def test_ignores_legacy_prefixed_numbers(self, db_session, main_branch):
        c = _customer(db_session)
        a = _account(db_session)
        _crv(db_session, 'CR-2026-06-0007', c, a, main_branch.id)
        assert generate_crv_number() == '00001'

    def test_is_five_digit_no_prefix(self, db_session, main_branch):
        n = generate_crv_number()
        assert n.isdigit() and len(n) == 5
