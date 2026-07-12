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
    """sss_row_for finds the correct bracket for a salary."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))

    # Test various salary points
    row_low = service.sss_row_for(tbl, Decimal('10000'))
    assert row_low is not None

    row_mid = service.sss_row_for(tbl, Decimal('30000'))
    assert row_mid is not None

    row_high = service.sss_row_for(tbl, Decimal('100000'))
    assert row_high is not None


def test_wht_bracket_for_salary(db_session):
    """WHT bracket lookup finds the correct bracket for a taxable amount."""
    seed_statutory_2026()

    # Test various taxable amounts in monthly frequency
    bracket_low = service.effective_wht_bracket('monthly', Decimal('5000'), date(2026, 6, 30))
    assert bracket_low is not None

    bracket_mid = service.effective_wht_bracket('monthly', Decimal('30000'), date(2026, 6, 30))
    assert bracket_mid is not None

    bracket_high = service.effective_wht_bracket('monthly', Decimal('100000'), date(2026, 6, 30))
    assert bracket_high is not None


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
