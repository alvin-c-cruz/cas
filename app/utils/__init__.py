"""
Utils package initialization.

Re-exports utilities from utils_helpers module for backward compatibility.
"""
from app.utils_helpers import PHT, ph_now, ph_datetime, utc_to_pht, format_ph_datetime, end_of_month

__all__ = ['PHT', 'ph_now', 'ph_datetime', 'utc_to_pht', 'format_ph_datetime', 'end_of_month',
           'format_line_qty']

_PCS_NAMES = ('pieces', 'piece', 'pc', 'pcs')
_PCS_CODES = ('PC', 'PCS', 'PCE')


def format_line_qty(item, blank=''):
    """Display a line item's quantity: whole number when the UoM is pieces
    (Pieces/piece/pcs), otherwise 4 decimals. `blank` is returned when qty is None.
    Duck-typed for any line item exposing quantity / unit_of_measure / uom_text.

    A piece quantity that is NOT whole keeps its decimals. '{:,.0f}' ROUNDS, so
    1.5 PCS printed as "2" and 0.25 PCS as "0" -- silently misstating a quantity
    on a document someone acts on. You cannot have a quarter of a piece by
    accident: if a fraction was entered, it was meant, and rounding it away is
    worse than the tidy display it buys. Trailing zeros are trimmed so it reads
    as entered (1.5, not 1.5000).
    """
    q = getattr(item, 'quantity', None)
    if q is None:
        return blank
    uom = getattr(item, 'unit_of_measure', None)
    name = ((getattr(uom, 'name', None) if uom else None) or getattr(item, 'uom_text', None) or '').strip().lower()
    code = ((getattr(uom, 'code', None) if uom else None) or '').strip().upper()
    is_pcs = name in _PCS_NAMES or code in _PCS_CODES
    if not is_pcs:
        return '{:,.4f}'.format(q)

    # Decimal, not float: the column is Numeric(15, 4) and a float round-trip
    # can make an exact value look fractional.
    from decimal import Decimal
    d = q if isinstance(q, Decimal) else Decimal(str(q))
    if d == d.to_integral_value():
        return '{:,.0f}'.format(q)
    return '{:,.4f}'.format(q).rstrip('0').rstrip('.')
