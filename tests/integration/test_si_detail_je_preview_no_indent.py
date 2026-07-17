"""Regression test for BUG-SI-DETAIL-JE-CREDIT-INDENT: the JE-preview table's credit-leg
account-title cell must not carry a hardcoded padding-left inline style (owner directive:
remove the indent entirely)."""
from datetime import date
from decimal import Decimal
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem


def test_je_preview_credit_row_has_no_padding_left_style(
        client, accountant_user, db_session, main_branch, revenue_account, vl_customer):
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-INDENT-TEST-0001',
        invoice_date=date(2026, 7, 17),
        due_date=date(2026, 8, 16),
        customer_id=vl_customer.id,
        customer_name=vl_customer.name,
        customer_tin=vl_customer.tin,
        status='draft',
    )
    item = SalesInvoiceItem(
        line_number=1, description='Test item',
        amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
        vat_category='V12', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        account_id=revenue_account.id,
    )
    inv.line_items.append(item)
    db_session.add(inv)
    db_session.commit()

    with client:
        client.post('/login', data={'username': accountant_user.username,
                                    'password': 'accountant123'}, follow_redirects=True)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/sales-invoices/{inv.id}')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'padding-left:24px' not in body, (
            'JE preview must not indent the credit-leg account title')
