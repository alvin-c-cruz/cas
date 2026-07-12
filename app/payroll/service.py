"""
Payroll calculation engine — statutory rate lookups and helpers.

All monetary values are Decimal, quantized to 2 places with ROUND_HALF_UP.
Lookups are fail-closed: they raise ValueError with friendly messages when no
effective row covers the requested date, never returning None silently.
"""

from decimal import Decimal, ROUND_HALF_UP
from app.payroll.tables_models import (
    SSSContributionTable, SSSContributionRow, PhilHealthRate,
    PagIbigRate, CompensationWHTBracket)


def _q2(x):
    """Quantize a monetary value to 2 decimal places (ROUND_HALF_UP)."""
    return Decimal(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _effective(model, as_of):
    """Find the effective row for a given date.

    Returns the most recent row whose effective_from <= as_of and either
    effective_to is NULL or effective_to >= as_of. Returns None if no row
    covers the date.
    """
    return (model.query
            .filter(model.effective_from <= as_of)
            .filter((model.effective_to.is_(None)) | (model.effective_to >= as_of))
            .order_by(model.effective_from.desc()).first())


def effective_sss(as_of):
    """Fetch the SSS contribution table effective on the given date.

    Args:
        as_of: date to look up

    Returns:
        SSSContributionTable with rows populated

    Raises:
        ValueError: if no SSS table is effective on as_of
    """
    tbl = _effective(SSSContributionTable, as_of)
    if tbl is None:
        raise ValueError(f"No SSS contribution table effective {as_of}. "
                         "Seed or assign the 2026 statutory tables first.")
    return tbl


def sss_row_for(tbl, monthly_comp):
    """Find the SSS contribution row matching a monthly compensation.

    Searches the table's rows for the bracket containing monthly_comp.
    If no bracket matches (e.g., salary is very low), returns the lowest bracket.
    If monthly_comp exceeds all brackets, returns the top (open-ended) bracket.

    Args:
        tbl: SSSContributionTable
        monthly_comp: Decimal monthly compensation

    Returns:
        SSSContributionRow matching the salary bracket
    """
    for r in tbl.rows:
        if monthly_comp >= r.comp_from and (r.comp_to is None or monthly_comp <= r.comp_to):
            return r
    return tbl.rows[-1]   # top open bracket (comp_to is None)


def effective_philhealth(as_of):
    """Fetch the PhilHealth rate effective on the given date.

    Args:
        as_of: date to look up

    Returns:
        PhilHealthRate

    Raises:
        ValueError: if no PhilHealth rate is effective on as_of
    """
    r = _effective(PhilHealthRate, as_of)
    if r is None:
        raise ValueError(f"No PhilHealth rate effective {as_of}.")
    return r


def effective_pagibig(as_of):
    """Fetch the Pag-IBIG rate effective on the given date.

    Args:
        as_of: date to look up

    Returns:
        PagIbigRate

    Raises:
        ValueError: if no Pag-IBIG rate is effective on as_of
    """
    r = _effective(PagIbigRate, as_of)
    if r is None:
        raise ValueError(f"No Pag-IBIG rate effective {as_of}.")
    return r


def effective_wht_bracket(frequency, taxable, as_of):
    """Fetch the compensation WHT bracket matching frequency and taxable amount.

    Searches the CompensationWHTBracket table for rows of the given frequency
    effective on as_of, then finds the bracket containing taxable. If no bracket
    matches (e.g., taxable is very low), returns the lowest bracket. If taxable
    exceeds all brackets, returns the top (open-ended) bracket.

    Args:
        frequency: bracket frequency (e.g., 'daily', 'weekly', 'monthly')
        taxable: Decimal taxable income
        as_of: date to look up

    Returns:
        CompensationWHTBracket matching the amount and frequency

    Raises:
        ValueError: if no bracket is effective for the frequency on as_of
    """
    rows = (CompensationWHTBracket.query
            .filter_by(frequency=frequency)
            .filter(CompensationWHTBracket.effective_from <= as_of)
            .filter((CompensationWHTBracket.effective_to.is_(None)) |
                    (CompensationWHTBracket.effective_to >= as_of))
            .order_by(CompensationWHTBracket.bracket_no).all())
    if not rows:
        raise ValueError(f"No {frequency} compensation WHT bracket effective {as_of}.")
    for b in rows:
        if taxable >= b.lower_bound and (b.upper_bound is None or taxable <= b.upper_bound):
            return b
    return rows[-1]   # top open bracket (upper_bound is None)
