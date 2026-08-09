"""Value formatting for document snapshots.

Two functions with deliberately different jobs:
  canonical() normalises for EQUALITY -- two snapshots of an unchanged document
              must compare equal as text.
  money()     formats for DISPLAY -- a printed form must read 4.20, not 4.2.

Generalised from _s/_money in app/sales_orders/revisions.py.
"""
from decimal import Decimal


def canonical(value):
    """JSON-safe CANONICAL string form. Dates ISO; Decimals normalised.

    Normalising is load-bearing: the same value stringifies differently depending
    on origin. A Numeric(15,4) column read back from SQLite gives
    Decimal('3000.0000') -> '3000.0000', while the form parser gives
    Decimal('3000') -> '3000'.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        # Decimal('-0') == Decimal('0') is True but they would render '-0' and
        # '0' -- equal values with unequal text is the exact failure this guards.
        if value == 0:
            value = abs(value)
        # format(..., 'f') avoids the scientific notation normalize() produces
        # for large integral values (Decimal('3000').normalize() is 3E+3).
        return format(value.normalize(), 'f')
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def money(value):
    """DISPLAY form for money: always 2 decimal places.

    Deliberately separate from canonical(), which collapses Decimal('4.20') to
    '4.2' -- correct for comparing snapshots, wrong on a printed form.
    """
    if value is None:
        return None
    return format(Decimal(str(value)).quantize(Decimal('0.01')), 'f')
