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

    Searches the table's rows (ordered ascending by comp_from) for the bracket
    containing monthly_comp. If monthly_comp is BELOW the lowest bracket's floor
    (comp_from), returns the lowest bracket (rows[0]). If monthly_comp is ABOVE
    every bracket's range (i.e. above the top, open-ended bracket's floor),
    returns the top bracket (rows[-1], comp_to is None).

    Args:
        tbl: SSSContributionTable
        monthly_comp: Decimal monthly compensation

    Returns:
        SSSContributionRow matching the salary bracket
    """
    for r in tbl.rows:
        if monthly_comp >= r.comp_from and (r.comp_to is None or monthly_comp <= r.comp_to):
            return r
    if monthly_comp < tbl.rows[0].comp_from:
        return tbl.rows[0]   # below the lowest bracket's floor -> lowest bracket
    return tbl.rows[-1]   # above all brackets -> top open bracket (comp_to is None)


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
    effective on as_of (ordered ascending by bracket_no), then finds the bracket
    containing taxable. If taxable is BELOW the lowest bracket's floor
    (lower_bound), returns the lowest bracket (rows[0]). If taxable is ABOVE
    every bracket's range (i.e. above the top, open-ended bracket's floor),
    returns the top bracket (rows[-1], upper_bound is None).

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
    if taxable < rows[0].lower_bound:
        return rows[0]   # below the lowest bracket's floor -> lowest bracket
    return rows[-1]   # above all brackets -> top open bracket (upper_bound is None)


def compute_statutory(monthly_basis, as_of):
    """Compute SSS, PhilHealth, and Pag-IBIG contributions for a monthly basis.

    Pure function: reads the effective statutory tables via the effective_*/
    sss_row_for lookups above and combines them into actual contribution
    amounts (employee and employer shares). No DB writes.

    Args:
        monthly_basis: Decimal monthly compensation basis
        as_of: date to look up effective statutory rates for

    Returns:
        dict with Decimal values (all _q2-quantized):
        {sss_ee, sss_er, sss_ec, philhealth_ee, philhealth_er,
         pagibig_ee, pagibig_er, sss_msc}
    """
    sss_tbl = effective_sss(as_of)
    r = sss_row_for(sss_tbl, monthly_basis)

    ph = effective_philhealth(as_of)
    clamped = min(max(monthly_basis, ph.income_floor), ph.income_ceiling)
    ph_total = _q2(clamped * ph.premium_rate)
    ph_ee = _q2(ph_total * ph.ee_share)

    pi = effective_pagibig(as_of)
    base = min(monthly_basis, pi.mc_ceiling)
    ee_rate = pi.lower_ee_rate if monthly_basis <= pi.bracket_threshold else pi.upper_ee_rate

    return {
        'sss_msc': r.msc,
        'sss_ee': _q2(r.ee_amount + r.ee_wisp),
        'sss_er': _q2(r.er_amount + r.er_wisp),
        'sss_ec': _q2(r.ec_amount),
        'philhealth_ee': ph_ee,
        'philhealth_er': _q2(ph_total - ph_ee),
        'pagibig_ee': _q2(base * ee_rate),
        'pagibig_er': _q2(base * pi.er_rate),
    }
