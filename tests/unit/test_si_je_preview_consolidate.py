"""The SI JE preview must consolidate lines posting to the same account into one
row (sum debit/credit), preserving first-seen order. A multi-line invoice with
several lines to the same revenue account should show that account once."""
from decimal import Decimal
import pytest

pytestmark = [pytest.mark.unit]


def test_consolidate_merges_same_account():
    from app.sales_invoices.views import _consolidate_je
    entries = [
        {'code': '40205', 'name': 'Rental Income', 'debit': Decimal('0.00'), 'credit': Decimal('8928.57')},
        {'code': '40205', 'name': 'Rental Income', 'debit': Decimal('0.00'), 'credit': Decimal('17857.14')},
        {'code': '20201', 'name': 'Output VAT Payable', 'debit': Decimal('0.00'), 'credit': Decimal('3214.29')},
        {'code': '10212', 'name': 'Creditable WHT Receivable', 'debit': Decimal('267.86'), 'credit': Decimal('0.00')},
        {'code': '10201', 'name': 'Accounts Receivable - Trade', 'debit': Decimal('29732.14'), 'credit': Decimal('0.00')},
    ]
    out = _consolidate_je(entries)
    # the two Rental Income lines merge into one
    rental = [e for e in out if e['code'] == '40205']
    assert len(rental) == 1
    assert rental[0]['credit'] == Decimal('26785.71')
    assert rental[0]['debit'] == Decimal('0.00')
    # order preserved, one fewer row
    assert [e['code'] for e in out] == ['40205', '20201', '10212', '10201']


def test_consolidate_noop_when_all_distinct():
    from app.sales_invoices.views import _consolidate_je
    entries = [
        {'code': '10201', 'name': 'AR', 'debit': Decimal('100.00'), 'credit': Decimal('0.00')},
        {'code': '40101', 'name': 'Sales', 'debit': Decimal('0.00'), 'credit': Decimal('100.00')},
    ]
    out = _consolidate_je(entries)
    assert len(out) == 2
