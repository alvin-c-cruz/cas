"""
Utils package initialization.

Re-exports utilities from utils_helpers module for backward compatibility.
"""
from app.utils_helpers import PHT, ph_now, ph_datetime, utc_to_pht, format_ph_datetime, end_of_month

__all__ = ['PHT', 'ph_now', 'ph_datetime', 'utc_to_pht', 'format_ph_datetime', 'end_of_month',
           'format_line_qty']

def format_line_qty(item, blank=''):
    """Display a line item's quantity as entered: no trailing zeros, up to the
    column's 4 decimal places. `blank` is returned when qty is None. Duck-typed
    for any line item exposing quantity / unit_of_measure / uom_text.

        12       -> '12'          (not '12.0000')
        1.5      -> '1.5'         (not '1.5000')
        1250.5555-> '1,250.5555'
        0.25     -> '0.25'

    The UoM is deliberately NOT consulted. This used to special-case pieces --
    whole for PC/PCS/PCE, 4 decimals for everything else -- which was wrong twice
    over. It ROUNDED (1.5 PCS printed as "2", 0.25 PCS as "0", misstating a
    quantity on a document people act on), and it left every other unit reading
    "12.0000 KG" when there was no decimal to show. A quantity should read the
    way it was entered whatever the unit, so there is no list of unit codes to
    keep in step with a client's master data.

    Trailing-zero stripping is safe on the formatted string because '.4f' always
    emits a decimal point, so rstrip('0') can never eat a significant zero from
    the integer part: '20.0000' -> '20.' -> '20'.
    """
    q = getattr(item, 'quantity', None)
    if q is None:
        return blank
    return '{:,.4f}'.format(q).rstrip('0').rstrip('.')
