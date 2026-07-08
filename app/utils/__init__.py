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
    Duck-typed for any line item exposing quantity / unit_of_measure / uom_text."""
    q = getattr(item, 'quantity', None)
    if q is None:
        return blank
    uom = getattr(item, 'unit_of_measure', None)
    name = ((getattr(uom, 'name', None) if uom else None) or getattr(item, 'uom_text', None) or '').strip().lower()
    code = ((getattr(uom, 'code', None) if uom else None) or '').strip().upper()
    is_pcs = name in _PCS_NAMES or code in _PCS_CODES
    return '{:,.0f}'.format(q) if is_pcs else '{:,.4f}'.format(q)
