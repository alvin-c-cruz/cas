"""CR JE sums same-account AR lines instead of one line per invoice
(BUG-CRV-CDV-MULTI-LINE-SAME-ACCOUNT-NOT-SUMMED)."""
from decimal import Decimal
from datetime import date
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _account(code, name='Ctrl'):
    from app.accounts.models import Account
    a = Account(code=code, name=name, account_type='Asset', normal_balance='Debit', is_active=True)
    db.session.add(a); db.session.commit()
    return a


def test_grouped_ar_lines_sums_same_account(db_session, main_branch, customer):
    from app.sales_invoices.models import SalesInvoice
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
    from app.cash_receipts.views import _grouped_ar_lines

    ar_default = _account('9201', 'AR Default')
    cash_acct = _account('9291', 'Cash on Hand')
    si1 = SalesInvoice(invoice_number='SI-GRP-0001', invoice_date=date(2026, 7, 1),
                       due_date=date(2026, 7, 31), customer_id=customer.id,
                       customer_name=customer.name, branch_id=main_branch.id, status='posted',
                       total_amount=Decimal('100.00'), balance=Decimal('100.00'), amount_paid=Decimal('0.00'))
    si2 = SalesInvoice(invoice_number='SI-GRP-0002', invoice_date=date(2026, 7, 2),
                       due_date=date(2026, 8, 1), customer_id=customer.id,
                       customer_name=customer.name, branch_id=main_branch.id, status='posted',
                       total_amount=Decimal('50.00'), balance=Decimal('50.00'), amount_paid=Decimal('0.00'))
    db.session.add_all([si1, si2]); db.session.commit()

    crv = CashReceiptVoucher(crv_number='CR-GRP-0001', crv_date=date(2026, 7, 10),
                             customer_id=customer.id, customer_name=customer.name,
                             branch_id=main_branch.id, cash_account_id=cash_acct.id, status='draft')
    db.session.add(crv); db.session.commit()
    crv.ar_lines.append(CRVArLine(line_number=1, invoice_id=si1.id, invoice_number=si1.invoice_number,
                                  original_balance=si1.balance, amount_applied=Decimal('100.00')))
    crv.ar_lines.append(CRVArLine(line_number=2, invoice_id=si2.id, invoice_number=si2.invoice_number,
                                  original_balance=si2.balance, amount_applied=Decimal('50.00')))
    db.session.commit()

    groups = _grouped_ar_lines(crv, ar_default)
    assert len(groups) == 1   # both invoices resolve to the same (default) AR account
    g = groups[0]
    assert g['account'].id == ar_default.id
    assert g['total'] == Decimal('150.00')
    assert g['refs'] == ['SI-GRP-0001', 'SI-GRP-0002']


def test_grouped_ar_lines_separates_different_accounts(db_session, main_branch, customer):
    from app.sales_invoices.models import SalesInvoice
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
    from app.cash_receipts.views import _grouped_ar_lines

    ar_default = _account('9202', 'AR Default 2')
    ar_override = _account('9203', 'AR Override')
    cash_acct = _account('9292', 'Cash on Hand 2')
    si1 = SalesInvoice(invoice_number='SI-GRP-0003', invoice_date=date(2026, 7, 1),
                       due_date=date(2026, 7, 31), customer_id=customer.id,
                       customer_name=customer.name, branch_id=main_branch.id, status='posted',
                       total_amount=Decimal('100.00'), balance=Decimal('100.00'), amount_paid=Decimal('0.00'),
                       ar_trade_account_id=ar_override.id)
    si2 = SalesInvoice(invoice_number='SI-GRP-0004', invoice_date=date(2026, 7, 2),
                       due_date=date(2026, 8, 1), customer_id=customer.id,
                       customer_name=customer.name, branch_id=main_branch.id, status='posted',
                       total_amount=Decimal('50.00'), balance=Decimal('50.00'), amount_paid=Decimal('0.00'))
    db.session.add_all([si1, si2]); db.session.commit()

    crv = CashReceiptVoucher(crv_number='CR-GRP-0002', crv_date=date(2026, 7, 10),
                             customer_id=customer.id, customer_name=customer.name,
                             branch_id=main_branch.id, cash_account_id=cash_acct.id, status='draft')
    db.session.add(crv); db.session.commit()
    crv.ar_lines.append(CRVArLine(line_number=1, invoice_id=si1.id, invoice_number=si1.invoice_number,
                                  original_balance=si1.balance, amount_applied=Decimal('100.00')))
    crv.ar_lines.append(CRVArLine(line_number=2, invoice_id=si2.id, invoice_number=si2.invoice_number,
                                  original_balance=si2.balance, amount_applied=Decimal('50.00')))
    db.session.commit()

    groups = _grouped_ar_lines(crv, ar_default)
    assert len(groups) == 2
    accounts = {g['account'].id for g in groups}
    assert accounts == {ar_override.id, ar_default.id}
