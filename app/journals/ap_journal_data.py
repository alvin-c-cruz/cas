"""Pure data layer for the columnar Accounts Payable Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
import calendar
from datetime import date, datetime


def _parse_iso(value):
    """Parse an ISO date string; return None on failure/empty."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def resolve_period(args, today):
    """Resolve the journal's date filter from request args.

    args: a mapping (request.args) with optional keys:
        mode='month'|'custom', year, month, date_from, date_to
    today: a date used for defaults.

    Returns dict: mode, year, month, date_from, date_to, label.
    Custom mode with unparseable dates falls back to the current month.
    """
    mode = args.get('mode', 'month')

    if mode == 'custom':
        df = _parse_iso(args.get('date_from'))
        dt = _parse_iso(args.get('date_to'))
        if df and dt:
            return {
                'mode': 'custom',
                'year': df.year,
                'month': df.month,
                'date_from': df,
                'date_to': dt,
                'label': f"From {df.strftime('%B %d, %Y')} to {dt.strftime('%B %d, %Y')}",
            }
        # bad/missing custom dates → fall through to month default

    try:
        year = int(args.get('year', today.year))
        month = int(args.get('month', today.month))
        if not 1 <= month <= 12:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    last_day = calendar.monthrange(year, month)[1]
    df = date(year, month, 1)
    dt = date(year, month, last_day)
    return {
        'mode': 'month',
        'year': year,
        'month': month,
        'date_from': df,
        'date_to': dt,
        'label': df.strftime('For the month of %B %Y'),
    }
