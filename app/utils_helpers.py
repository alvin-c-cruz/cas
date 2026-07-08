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
