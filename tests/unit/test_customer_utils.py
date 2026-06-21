"""Unit tests for customer AR-aging and creditable-WHT helpers."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.utils import ph_now
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.withholding_tax.models import WithholdingTax
from app.customers.utils import compute_ar_aging, compute_creditable_wht_ytd


def _customer(db_session, code='C001'):
    c = Customer(code=code, name=f'Customer {code}', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _invoice(db_session, customer, number, days_to_due, status='posted',
             balance='1000.00'):
    """Create an SI whose due_date is `days_to_due` from today (negative = overdue)."""
    due = ph_now().date() + timedelta(days=days_to_due)
    inv = SalesInvoice(
        invoice_number=number,
        invoice_date=ph_now().date(),
        due_date=due,
        customer_id=customer.id,
        customer_name=customer.name,
        status=status,
        balance=Decimal(balance),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.mark.unit
def test_ar_aging_buckets_by_days_overdue(db_session):
    c = _customer(db_session)
    _invoice(db_session, c, 'SI-1', days_to_due=10, balance='100.00')    # current
    _invoice(db_session, c, 'SI-2', days_to_due=-15, balance='200.00')   # 1-30
    _invoice(db_session, c, 'SI-3', days_to_due=-45, balance='300.00')   # 31-60
    _invoice(db_session, c, 'SI-4', days_to_due=-75, balance='400.00')   # 61-90
    _invoice(db_session, c, 'SI-5', days_to_due=-120, balance='500.00')  # 90+

    aging = compute_ar_aging(c.id)

    assert aging['current'] == Decimal('100.00')
    assert aging['1_30'] == Decimal('200.00')
    assert aging['31_60'] == Decimal('300.00')
    assert aging['61_90'] == Decimal('400.00')
    assert aging['90_plus'] == Decimal('500.00')
    assert aging['total'] == Decimal('1500.00')


@pytest.mark.unit
def test_ar_aging_excludes_draft_and_paid(db_session):
    c = _customer(db_session)
    _invoice(db_session, c, 'SI-1', days_to_due=10, status='posted', balance='100.00')
    _invoice(db_session, c, 'SI-2', days_to_due=10, status='draft', balance='999.00')
    _invoice(db_session, c, 'SI-3', days_to_due=10, status='paid', balance='888.00')
    _invoice(db_session, c, 'SI-4', days_to_due=-5, status='partially_paid', balance='50.00')

    aging = compute_ar_aging(c.id)

    assert aging['current'] == Decimal('100.00')   # only the posted one
    assert aging['1_30'] == Decimal('50.00')       # partially_paid counts
    assert aging['total'] == Decimal('150.00')


@pytest.mark.unit
def test_creditable_wht_ytd_groups_by_code(db_session):
    c = _customer(db_session)
    wt = WithholdingTax(code='WC010', name='Professional 10%', rate=Decimal('10.00'),
                        is_active=True)
    db_session.add(wt)
    db_session.commit()

    inv = _invoice(db_session, c, 'SI-1', days_to_due=10, status='posted')
    db_session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1,
                                    description='Service A', wt_id=wt.id,
                                    wt_amount=Decimal('30.00')))
    db_session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=2,
                                    description='Service B', wt_id=wt.id,
                                    wt_amount=Decimal('20.00')))
    db_session.commit()

    rows = compute_creditable_wht_ytd(c.id)

    assert len(rows) == 1
    assert rows[0]['code'] == 'WC010'
    assert rows[0]['name'] == 'Professional 10%'   # name is rendered in the UI
    assert rows[0]['total'] == Decimal('50.00')


@pytest.mark.unit
def test_creditable_wht_ytd_posted_only_and_null_wt_excluded(db_session):
    c = _customer(db_session)
    wt = WithholdingTax(code='WC010', name='Professional 10%', rate=Decimal('10.00'),
                        is_active=True)
    db_session.add(wt)
    db_session.commit()

    posted = _invoice(db_session, c, 'SI-1', days_to_due=10, status='posted')
    draft = _invoice(db_session, c, 'SI-2', days_to_due=10, status='draft')
    db_session.add(SalesInvoiceItem(invoice_id=posted.id, line_number=1,
                                    description='Billed', wt_id=wt.id,
                                    wt_amount=Decimal('30.00')))
    db_session.add(SalesInvoiceItem(invoice_id=posted.id, line_number=2,
                                    description='No WHT line', wt_id=None,
                                    wt_amount=Decimal('0.00')))
    db_session.add(SalesInvoiceItem(invoice_id=draft.id, line_number=1,
                                    description='Draft line', wt_id=wt.id,
                                    wt_amount=Decimal('99.00')))
    db_session.commit()

    rows = compute_creditable_wht_ytd(c.id)

    assert len(rows) == 1
    assert rows[0]['total'] == Decimal('30.00')   # draft + null-wt excluded
