"""Integration tests for the customer detail page."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.utils import ph_now
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice


def _customer(db_session, code='C001'):
    c = Customer(code=code, name='Acme Trading', tin='123-456-789-000',
                 payment_terms='Net 30', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _invoice(db_session, customer, number, status='posted', balance='1000.00',
             days_to_due=10):
    inv = SalesInvoice(
        invoice_number=number,
        invoice_date=ph_now().date(),
        due_date=ph_now().date() + timedelta(days=days_to_due),
        customer_id=customer.id,
        customer_name=customer.name,
        status=status,
        subtotal=Decimal('1120.00'),
        vat_amount=Decimal('120.00'),
        withholding_tax_amount=Decimal('20.00'),
        total_amount=Decimal('1100.00'),
        balance=Decimal(balance),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.mark.integration
def test_detail_overview_renders_for_accountant(client, db_session, accountant_user, main_branch,
                                                 login_user):
    c = _customer(db_session)
    login_user(client, 'accountant', 'accountant123')

    resp = client.get(f'/customers/{c.id}')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Acme Trading' in body
    assert 'AR Aging' in body
    assert 'Creditable WHT' in body


@pytest.mark.integration
def test_detail_overview_renders_for_admin(client, db_session, admin_user, main_branch, login_user):
    c = _customer(db_session)
    login_user(client, 'admin', 'admin123')

    resp = client.get(f'/customers/{c.id}?tab=overview')

    assert resp.status_code == 200


@pytest.mark.integration
def test_detail_invoices_tab_lists_invoices(client, db_session, accountant_user, main_branch,
                                            login_user):
    c = _customer(db_session)
    _invoice(db_session, c, 'SI-2026-06-0001')
    login_user(client, 'accountant', 'accountant123')

    resp = client.get(f'/customers/{c.id}?tab=invoices')

    assert resp.status_code == 200
    assert 'SI-2026-06-0001' in resp.data.decode()


@pytest.mark.integration
def test_detail_invoices_status_filter(client, db_session, accountant_user, main_branch, login_user):
    c = _customer(db_session)
    _invoice(db_session, c, 'SI-POSTED', status='posted')
    _invoice(db_session, c, 'SI-DRAFT', status='draft')
    login_user(client, 'accountant', 'accountant123')

    resp = client.get(f'/customers/{c.id}?tab=invoices&status=draft')

    body = resp.data.decode()
    assert 'SI-DRAFT' in body
    assert 'SI-POSTED' not in body


def _posted_crv(db_session, customer, branch, cash_account, invoice,
                crv_number, crv_date, amount, status='posted'):
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
    crv = CashReceiptVoucher(
        branch_id=branch.id, crv_number=crv_number, crv_date=crv_date,
        customer_id=customer.id, customer_name=customer.name,
        cash_account_id=cash_account.id, status=status,
        total_ar_applied=Decimal(str(amount)), total_amount=Decimal(str(amount)),
    )
    crv.ar_lines.append(CRVArLine(
        line_number=1, invoice_id=invoice.id, invoice_number=invoice.invoice_number,
        original_balance=Decimal(str(invoice.total_amount)), amount_applied=Decimal(str(amount)),
    ))
    db_session.add(crv)
    db_session.commit()
    return crv


@pytest.mark.integration
def test_invoices_tab_shows_collectible_collected_balance_columns(
        client, db_session, accountant_user, main_branch, cash_account, login_user):
    from datetime import date
    c = _customer(db_session)
    inv = _invoice(db_session, c, 'SI-COLL-01', balance='800.00')
    inv.amount_paid = Decimal('300.00')
    db_session.commit()
    _posted_crv(db_session, c, main_branch, cash_account, inv,
                'CRV-2026-07-0005', date(2026, 7, 15), '300.00')
    login_user(client, 'accountant', 'accountant123')

    resp = client.get(f'/customers/{c.id}?tab=invoices')

    assert resp.status_code == 200
    body = resp.data.decode()
    # new columns replace the old subtotal/vat/wht/net breakdown
    assert 'AMOUNT COLLECTIBLE' in body
    assert 'COLLECTED' in body
    assert 'BALANCE' in body
    assert 'OUTPUT VAT' not in body
    assert 'NET AMOUNT' not in body
    # the settling CRV is available to the collected-cell popup
    assert 'CRV-2026-07-0005' in body
    assert '15 Jul 2026' in body


@pytest.mark.integration
def test_invoices_tab_draft_crv_not_in_collections(
        client, db_session, accountant_user, main_branch, cash_account, login_user):
    from datetime import date
    c = _customer(db_session)
    inv = _invoice(db_session, c, 'SI-COLL-02', balance='1100.00')
    _posted_crv(db_session, c, main_branch, cash_account, inv,
                'CRV-DRAFT-9', date(2026, 7, 16), '250.00', status='draft')
    login_user(client, 'accountant', 'accountant123')

    resp = client.get(f'/customers/{c.id}?tab=invoices')

    assert resp.status_code == 200
    assert 'CRV-DRAFT-9' not in resp.data.decode()


@pytest.mark.integration
def test_detail_404_for_unknown_customer(client, db_session, accountant_user, main_branch, login_user):
    login_user(client, 'accountant', 'accountant123')
    resp = client.get('/customers/99999')
    assert resp.status_code == 404


@pytest.mark.integration
def test_list_links_point_to_detail(client, db_session, accountant_user, main_branch, login_user):
    c = _customer(db_session)
    login_user(client, 'accountant', 'accountant123')

    resp = client.get('/customers')

    body = resp.data.decode()
    assert f'/customers/{c.id}"' in body          # detail link present
    # the code/name cells must no longer link to the edit page
    assert f'/customers/{c.id}/edit" class="customer-link"' not in body
