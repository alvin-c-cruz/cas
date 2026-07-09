import pytest
from datetime import date, timedelta
from decimal import Decimal
from app.quotations.models import Quotation, QuotationItem

pytestmark = [pytest.mark.usefixtures("app"), pytest.mark.integration, pytest.mark.quotations]


def _quote(treatment, amounts):
    q = Quotation(quotation_number='QTN-T', quotation_date=date(2026, 7, 9),
                  valid_until=date(2026, 8, 9), customer_id=1, customer_name='Acme',
                  vat_treatment=treatment, status='draft')
    for i, a in enumerate(amounts, start=1):
        li = QuotationItem(line_number=i, amount=Decimal(str(a)), vat_rate=Decimal('12'))
        li.calculate_amounts()
        q.line_items.append(li)
    q.calculate_totals()
    return q


def test_calculate_totals_three_treatments():
    # inclusive: 1120 gross -> net 1000, vat 120, total 1120
    inc = _quote('inclusive', ['1120.00'])
    assert inc.subtotal == Decimal('1120.00') and inc.vat_amount == Decimal('120.00')
    assert inc.total_amount == Decimal('1120.00')
    # exclusive: 1000 net -> vat 120, total 1120
    exc = _quote('exclusive', ['1000.00'])
    assert exc.subtotal == Decimal('1000.00') and exc.vat_amount == Decimal('120.00')
    assert exc.total_amount == Decimal('1120.00')
    # zero_rated: 1000 -> vat 0, total 1000
    zr = _quote('zero_rated', ['1000.00'])
    assert zr.vat_amount == Decimal('0.00') and zr.total_amount == Decimal('1000.00')


def test_is_expired_only_when_sent_and_past():
    q = _quote('inclusive', ['100.00'])
    q.status = 'sent'; q.valid_until = date.today() - timedelta(days=1)
    assert q.is_expired is True
    q.status = 'draft'
    assert q.is_expired is False           # draft is never "expired"
    q.status = 'sent'; q.valid_until = date.today() + timedelta(days=5)
    assert q.is_expired is False
