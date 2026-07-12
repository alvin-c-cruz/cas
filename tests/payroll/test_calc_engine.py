"""
Test payroll calculation engine (service.py) - statutory rate lookups and seeding.
"""

import pytest
from datetime import date
from decimal import Decimal
from app.payroll import service
from app.seeds.statutory_2026 import seed_statutory_2026


def test_effective_lookup_fails_closed(db_session):
    """Lookup raises ValueError when no effective row covers the date."""
    with pytest.raises(ValueError, match="No SSS contribution table"):
        service.effective_sss(date(2026, 6, 30))


def test_seed_then_lookup(db_session):
    """After seeding, lookups return the 2026 statutory rows."""
    seed_statutory_2026()

    # SSS lookup
    tbl = service.effective_sss(date(2026, 6, 30))
    row = service.sss_row_for(tbl, Decimal('30000'))
    assert row.ee_amount + row.ee_wisp > 0

    # PhilHealth lookup
    ph = service.effective_philhealth(date(2026, 6, 30))
    assert ph.premium_rate == Decimal('0.0500')

    # Pag-IBIG lookup
    pagibig = service.effective_pagibig(date(2026, 6, 30))
    assert pagibig.lower_ee_rate > 0

    # WHT bracket lookup
    wht = service.effective_wht_bracket('monthly', Decimal('30000'), date(2026, 6, 30))
    assert wht is not None


def test_philhealth_lookup_fails_closed(db_session):
    """PhilHealth lookup raises ValueError when no effective rate."""
    with pytest.raises(ValueError, match="No PhilHealth rate effective"):
        service.effective_philhealth(date(2026, 6, 30))


def test_pagibig_lookup_fails_closed(db_session):
    """Pag-IBIG lookup raises ValueError when no effective rate."""
    with pytest.raises(ValueError, match="No Pag-IBIG rate effective"):
        service.effective_pagibig(date(2026, 6, 30))


def test_wht_lookup_fails_closed(db_session):
    """WHT bracket lookup raises ValueError when no effective bracket for frequency."""
    with pytest.raises(ValueError, match="No monthly compensation WHT bracket effective"):
        service.effective_wht_bracket('monthly', Decimal('30000'), date(2026, 6, 30))


def test_seed_idempotent(db_session):
    """Seeding twice does not create duplicate rows."""
    seed_statutory_2026()
    sss_count_1 = service.SSSContributionTable.query.filter_by(effective_from=date(2026, 1, 1)).count()

    seed_statutory_2026()
    sss_count_2 = service.SSSContributionTable.query.filter_by(effective_from=date(2026, 1, 1)).count()

    assert sss_count_1 == sss_count_2


def test_sss_row_for_bracket_lookup(db_session):
    """sss_row_for finds the SPECIFIC correct bracket for a salary, not just a truthy row."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))

    # Mid-range value: lands in the published ₱30k anchor bracket.
    row_mid = service.sss_row_for(tbl, Decimal('30000'))
    assert row_mid.comp_from == Decimal('29750')

    # Exactly at a bracket's lower boundary: must match that bracket, not the
    # one below it.
    row_boundary = service.sss_row_for(tbl, Decimal('29750'))
    assert row_boundary.comp_from == Decimal('29750')

    # One cent below that boundary: must match the PRECEDING bracket (proves
    # the brackets are contiguous with no gap at the boundary).
    row_just_below = service.sss_row_for(tbl, Decimal('29749.99'))
    assert row_just_below.comp_from == Decimal('21000')

    # Above all brackets: top open-ended bracket (comp_to is None).
    row_high = service.sss_row_for(tbl, Decimal('100000'))
    assert row_high.comp_from == Decimal('40000')
    assert row_high.comp_to is None

    # Below the lowest bracket's floor (lowest comp_from is 1000): must fall
    # back to the LOWEST bracket, not the highest (regression for the
    # rows[-1]-fallback bug).
    row_below = service.sss_row_for(tbl, Decimal('500'))
    assert row_below.comp_from == Decimal('1000')


def test_wht_bracket_for_salary(db_session):
    """WHT bracket lookup finds the SPECIFIC correct bracket, not just a truthy match."""
    seed_statutory_2026()

    # Mid-range value: bracket 2 (15% rate).
    bracket_mid = service.effective_wht_bracket('monthly', Decimal('30000'), date(2026, 6, 30))
    assert bracket_mid.bracket_no == 2

    # Exactly at bracket 2's lower boundary (the design anchor: 20833): must
    # match bracket 2, not bracket 1 or 3 -- this is the critical regression
    # test for the off-by-one bug.
    bracket_at_boundary = service.effective_wht_bracket('monthly', Decimal('20833'), date(2026, 6, 30))
    assert bracket_at_boundary.bracket_no == 2

    # One peso below that boundary: must match bracket 1 (proves brackets 1
    # and 2 are contiguous with no gap).
    bracket_just_below = service.effective_wht_bracket('monthly', Decimal('20832'), date(2026, 6, 30))
    assert bracket_just_below.bracket_no == 1

    # A fractional value that used to fall in the pre-fix gap (20833.01 -
    # 20833.99): must now match bracket 2.
    bracket_in_old_gap = service.effective_wht_bracket('monthly', Decimal('20833.50'), date(2026, 6, 30))
    assert bracket_in_old_gap.bracket_no == 2

    # Exactly at bracket 3's lower boundary (33333): must match bracket 3.
    bracket_3_boundary = service.effective_wht_bracket('monthly', Decimal('33333'), date(2026, 6, 30))
    assert bracket_3_boundary.bracket_no == 3

    # Above all brackets: top open-ended bracket (bracket 4, 25%).
    bracket_high = service.effective_wht_bracket('monthly', Decimal('100000'), date(2026, 6, 30))
    assert bracket_high.bracket_no == 4
    assert bracket_high.upper_bound is None

    # Below the lowest bracket's floor (bracket 1's lower_bound is 0): must
    # fall back to the LOWEST bracket, not the highest (regression for the
    # rows[-1]-fallback bug).
    bracket_below = service.effective_wht_bracket('monthly', Decimal('-100'), date(2026, 6, 30))
    assert bracket_below.bracket_no == 1


def test_effective_lookup_respects_effective_dates(db_session):
    """Lookups only return rows that are effective on the requested date."""
    from datetime import date, timedelta
    seed_statutory_2026()

    # Before 2026-01-01 should fail
    with pytest.raises(ValueError):
        service.effective_sss(date(2025, 12, 31))

    # On 2026-01-01 should succeed
    tbl = service.effective_sss(date(2026, 1, 1))
    assert tbl is not None

    # Far future should still return the same table (effective_to is None)
    tbl_future = service.effective_sss(date(2030, 12, 31))
    assert tbl_future is not None
