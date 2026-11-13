"""
Utility functions for the CAS application.
"""
import calendar
from datetime import datetime, timezone, timedelta

# Philippine Standard Time (UTC+8)
PHT = timezone(timedelta(hours=8))


def end_of_month(d):
    """Return the last calendar day of d's month."""
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def this_month_iso():
    """(first day, last day) of the current PHT month as ISO strings -- the default
    From / To of the transaction lists (owner, 22 Oct 2026)."""
    today = ph_now().date()
    return today.replace(day=1).isoformat(), end_of_month(today).isoformat()


def list_date_range(args, q):
    """(date_from, date_to, all_dates) for a transaction list's From / To.

    The lists open on the current month (owner, 22 Oct 2026). Any search text -- a document
    number or a name -- looks across all dates and ignores From / To, which the filter forms
    always submit (owner, 12 Nov 2026: "S8 A", NAME-1 "A", S8-ALL "A"). Then both come back
    blank, so the boxes show that no period applies. `args` is request.args."""
    if (q or '').strip():
        return '', '', True
    bom, eom = this_month_iso()
    return args.get('date_from', bom), args.get('date_to', eom), False


def journal_period(date_from, date_to):
    """The period a list's Download Journal link carries: the list's own From / To, or the
    current month while a search spans all dates (the download needs a real period)."""
    bom, eom = this_month_iso()
    return date_from or bom, date_to or eom


def list_period_context(args):
    """Template values for a list's search and From / To: q, date_from, date_to, all_dates
    (the page says "Searching all dates"), and journal_from / journal_to for Download Journal."""
    q = (args.get('q') or '').strip()
    date_from, date_to, all_dates = list_date_range(args, q)
    journal_from, journal_to = journal_period(date_from, date_to)
    return {'q': q, 'date_from': date_from, 'date_to': date_to, 'all_dates': all_dates,
            'journal_from': journal_from, 'journal_to': journal_to}


def ph_now():
    """
    Get current datetime in Philippine Standard Time (UTC+8).

    Returns:
        datetime: Current datetime in PHT timezone
    """
    return datetime.now(PHT)


def ph_datetime(*args, **kwargs):
    """
    Create a datetime object in Philippine Standard Time.

    Args:
        Same as datetime() constructor

    Returns:
        datetime: Datetime object with PHT timezone
    """
    dt = datetime(*args, **kwargs)
    return dt.replace(tzinfo=PHT)


def utc_to_pht(dt):
    """
    Convert UTC datetime to Philippine Standard Time.

    Args:
        dt (datetime): UTC datetime object

    Returns:
        datetime: Datetime converted to PHT
    """
    if dt.tzinfo is None:
        # Assume UTC if no timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PHT)


def format_ph_datetime(dt, format_string='%Y-%m-%d %I:%M:%S %p'):
    """
    Format datetime in Philippine Standard Time.

    Args:
        dt (datetime): Datetime object to format
        format_string (str): strftime format string

    Returns:
        str: Formatted datetime string
    """
    if dt.tzinfo is None:
        # Assume UTC if no timezone
        dt = dt.replace(tzinfo=timezone.utc)

    pht_dt = dt.astimezone(PHT)
    return pht_dt.strftime(format_string)
