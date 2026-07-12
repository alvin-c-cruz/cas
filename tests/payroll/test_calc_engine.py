"""
Test payroll calculation engine (service.py) - statutory rate lookups and seeding.
"""

import pytest
from datetime import date
from decimal import Decimal
from app import db
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


def test_statutory_anchors_30k(db_session):
    """compute_statutory produces the correct SSS/PhilHealth/Pag-IBIG split at 30,000."""
    seed_statutory_2026()
    s = service.compute_statutory(Decimal('30000'), date(2026, 6, 30))
    # Reference figures — confirm vs current circulars at build time:
    assert s['sss_ee'] == Decimal('1500.00')
    assert s['sss_er'] == Decimal('3000.00')
    assert s['sss_ec'] == Decimal('30.00')
    assert s['philhealth_ee'] == Decimal('750.00')   # 30000*0.05/2
    assert s['philhealth_er'] == Decimal('750.00')
    assert s['pagibig_ee'] == Decimal('200.00')       # min(30000,10000)*0.02
    assert s['pagibig_er'] == Decimal('200.00')


def test_statutory_returns_all_expected_keys(db_session):
    """compute_statutory's dict has exactly the documented keys, all Decimal."""
    seed_statutory_2026()
    s = service.compute_statutory(Decimal('30000'), date(2026, 6, 30))
    expected_keys = {
        'sss_ee', 'sss_er', 'sss_ec', 'philhealth_ee', 'philhealth_er',
        'pagibig_ee', 'pagibig_er', 'sss_msc',
    }
    assert set(s.keys()) == expected_keys
    for v in s.values():
        assert isinstance(v, Decimal)


def test_philhealth_clamps(db_session):
    """PhilHealth premium is clamped to [income_floor, income_ceiling] before the rate applies."""
    seed_statutory_2026()
    lo = service.compute_statutory(Decimal('8000'), date(2026, 6, 30))
    assert lo['philhealth_ee'] == Decimal('250.00')   # floor 10000 -> 500 total /2
    hi = service.compute_statutory(Decimal('120000'), date(2026, 6, 30))
    assert hi['philhealth_ee'] == Decimal('2500.00')  # ceiling 100000 -> 5000 /2


def test_philhealth_floor_boundary_exact(db_session):
    """Monthly basis exactly AT the floor is NOT further reduced -- same result as clamped-from-below."""
    seed_statutory_2026()
    at_floor = service.compute_statutory(Decimal('10000'), date(2026, 6, 30))
    assert at_floor['philhealth_ee'] == Decimal('250.00')
    assert at_floor['philhealth_er'] == Decimal('250.00')

    just_below = service.compute_statutory(Decimal('9999.99'), date(2026, 6, 30))
    assert just_below['philhealth_ee'] == Decimal('250.00')
    assert just_below['philhealth_er'] == Decimal('250.00')


def test_philhealth_ceiling_boundary_exact(db_session):
    """Monthly basis exactly AT the ceiling is NOT clamped down -- same result as clamped-from-above."""
    seed_statutory_2026()
    at_ceiling = service.compute_statutory(Decimal('100000'), date(2026, 6, 30))
    assert at_ceiling['philhealth_ee'] == Decimal('2500.00')
    assert at_ceiling['philhealth_er'] == Decimal('2500.00')

    just_above = service.compute_statutory(Decimal('100000.01'), date(2026, 6, 30))
    assert just_above['philhealth_ee'] == Decimal('2500.00')
    assert just_above['philhealth_er'] == Decimal('2500.00')


def test_pagibig_threshold_boundary_exact(db_session):
    """Pag-IBIG rate selection at the bracket_threshold uses the LOWER rate (inclusive <=),
    and one centavo above switches to the UPPER rate -- proves no off-by-one gap/overlap."""
    seed_statutory_2026()
    at_threshold = service.compute_statutory(Decimal('1500'), date(2026, 6, 30))
    assert at_threshold['pagibig_ee'] == Decimal('15.00')   # 1500 * 1% (lower rate)
    assert at_threshold['pagibig_er'] == Decimal('30.00')   # 1500 * 2% (er_rate, always upper)

    just_above = service.compute_statutory(Decimal('1500.01'), date(2026, 6, 30))
    assert just_above['pagibig_ee'] == Decimal('30.00')     # 1500.01 * 2% (upper rate) rounds to 30.00

    just_below = service.compute_statutory(Decimal('1499.99'), date(2026, 6, 30))
    assert just_below['pagibig_ee'] == Decimal('15.00')     # 1499.99 * 1% (lower rate) rounds to 15.00


def test_pagibig_mc_ceiling_boundary(db_session):
    """Pag-IBIG contribution base is capped at mc_ceiling; below it, the full salary is used."""
    seed_statutory_2026()
    below_ceiling = service.compute_statutory(Decimal('9000'), date(2026, 6, 30))
    assert below_ceiling['pagibig_ee'] == Decimal('180.00')  # 9000 * 2% (unclamped)

    at_ceiling = service.compute_statutory(Decimal('10000'), date(2026, 6, 30))
    assert at_ceiling['pagibig_ee'] == Decimal('200.00')     # 10000 * 2% (base == ceiling, not yet clamped)

    above_ceiling = service.compute_statutory(Decimal('10000.01'), date(2026, 6, 30))
    assert above_ceiling['pagibig_ee'] == Decimal('200.00')  # base clamped down to 10000


def test_sss_bracket_transition_via_compute_statutory(db_session):
    """A one-centavo change across an SSS bracket boundary changes the computed contribution
    -- proves compute_statutory composes sss_row_for's boundary logic correctly, not just
    that sss_row_for itself is correct in isolation."""
    seed_statutory_2026()
    just_below = service.compute_statutory(Decimal('29749.99'), date(2026, 6, 30))
    assert just_below['sss_ee'] == Decimal('1250.00')  # preceding bracket (comp_from 21000, msc 25000)

    at_boundary = service.compute_statutory(Decimal('29750'), date(2026, 6, 30))
    assert at_boundary['sss_ee'] == Decimal('1500.00')  # critical 30k-anchor bracket


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


# ---------------------------------------------------------------------------
# compute_line -- taxable comp + TRAIN compensation WHT (Task 4, P1 exit gate)
# ---------------------------------------------------------------------------

def test_wht_monthly_anchor(db_session):
    """compute_line combines statutory + TRAIN WHT correctly for a plain monthly
    employee -- pins the exact figures as a regression anchor for the whole
    calc-engine composition."""
    seed_statutory_2026()
    line = service.compute_line(dict(
        pay_basis='monthly', monthly_rate=Decimal('40000'), days=0, hours=0,
        ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='monthly', period_end=date(2026, 6, 30),
        semi_timing='second_cutoff'))
    # taxable = 40000 - statutory EE; assert WHT via monthly bracket (base + excess*rate)
    assert line['taxable_comp'] > 0
    assert line['wht'] > 0
    assert line['wht_bracket_id'] is not None
    # net = gross - EE statutory - wht - loans(0)
    assert line['net_pay'] == service._q2(
        line['gross_pay'] - line['statutory']['sss_ee']
        - line['statutory']['philhealth_ee'] - line['statutory']['pagibig_ee']
        - line['wht'])
    # Pin the exact figures.
    assert line['basic_gross'] == Decimal('40000.00')
    assert line['gross_pay'] == Decimal('40000.00')
    assert line['statutory']['sss_ee'] == Decimal('2000.00')
    assert line['statutory']['philhealth_ee'] == Decimal('1000.00')
    assert line['statutory']['pagibig_ee'] == Decimal('200.00')
    assert line['taxable_comp'] == Decimal('36800.00')   # 40000 - 3200 EE statutory
    assert line['wht'] == Decimal('2568.40')              # bracket 3: 1875 + (36800-33333)*0.20
    assert line['net_pay'] == Decimal('34231.60')


def test_mwe_is_wht_exempt(db_session):
    """A minimum-wage earner (MWE) is WHT-exempt (taxable_comp=0, wht=0) but
    SSS/PhilHealth/Pag-IBIG still apply -- this exact rule was gotten wrong
    once before in this codebase for a different feature; the MWE branch must
    NOT zero out the statutory deductions too. Uses an explicit daily_rate key
    (rather than reusing monthly_rate, which would trivially zero gross and
    make this test vacuous)."""
    seed_statutory_2026()
    line = service.compute_line(dict(
        pay_basis='daily', monthly_rate=Decimal('0'), daily_rate=Decimal('645'),
        days=22, hours=0,
        ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=True, pay_frequency='daily', period_end=date(2026, 6, 30),
        semi_timing='second_cutoff'))
    assert line['taxable_comp'] == Decimal('0.00')
    assert line['wht'] == Decimal('0.00')
    assert line['wht_bracket_id'] is None
    # MWE exemption must NOT zero out statutory deductions.
    assert line['statutory']['sss_ee'] == Decimal('712.50')
    assert line['statutory']['philhealth_ee'] == Decimal('354.75')
    assert line['statutory']['pagibig_ee'] == Decimal('200.00')
    assert line['net_pay'] == service._q2(
        line['gross_pay'] - line['statutory']['sss_ee']
        - line['statutory']['philhealth_ee'] - line['statutory']['pagibig_ee'])
    assert line['net_pay'] == Decimal('12922.75')


def test_compute_line_returns_all_expected_keys(db_session):
    """compute_line's dict has exactly the documented keys."""
    seed_statutory_2026()
    line = service.compute_line(dict(
        pay_basis='monthly', monthly_rate=Decimal('30000'), days=0, hours=0,
        ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='monthly', period_end=date(2026, 6, 30),
        semi_timing='second_cutoff'))
    expected_keys = {'basic_gross', 'gross_pay', 'statutory', 'taxable_comp',
                      'wht', 'wht_bracket_id', 'net_pay', 'sss_msc'}
    assert set(line.keys()) == expected_keys
    assert line['sss_msc'] == line['statutory']['sss_msc']


def test_gross_includes_ot_holiday_and_allowances(db_session):
    """gross_pay = basic + ot_pay + holiday_pay + taxable_allowance + nontax_allowance."""
    seed_statutory_2026()
    line = service.compute_line(dict(
        pay_basis='monthly', monthly_rate=Decimal('20000'), days=0, hours=0,
        ot_pay=Decimal('1500'), holiday_pay=Decimal('800'),
        taxable_allowance=Decimal('1000'), nontax_allowance=Decimal('500'),
        is_mwe=False, pay_frequency='monthly', period_end=date(2026, 6, 30),
        semi_timing='second_cutoff'))
    assert line['basic_gross'] == Decimal('20000.00')
    assert line['gross_pay'] == Decimal('23800.00')   # 20000+1500+800+1000+500


def test_taxable_comp_clamped_at_zero_when_statutory_exceeds_basic(db_session):
    """A partial-period daily worker's statutory is computed on the FULL-MONTH
    proxy (daily_rate*22), which can exceed the actual (few-days) basic pay --
    taxable_comp must clamp at 0.00, never go negative, even for a non-MWE
    employee."""
    seed_statutory_2026()
    line = service.compute_line(dict(
        pay_basis='daily', monthly_rate=Decimal('0'), daily_rate=Decimal('1200'),
        days=1, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='daily', period_end=date(2026, 6, 30),
        semi_timing='second_cutoff'))
    assert line['basic_gross'] == Decimal('1200.00')          # 1200 * 1 day
    assert line['statutory']['sss_ee'] == Decimal('1250.00')  # off the 26400 full-month proxy
    assert line['taxable_comp'] == Decimal('0.00')
    assert line['wht'] == Decimal('0.00')
    assert line['wht_bracket_id'] is None


def test_daily_basis_monthly_basis_proxy_ignores_actual_days(db_session):
    """The daily-basis monthly_basis proxy is ALWAYS daily_rate * 22 for
    statutory purposes, regardless of the employee's actual days worked this
    period -- this is the source of the taxable-clamp edge case above."""
    seed_statutory_2026()
    full_month = service.compute_line(dict(
        pay_basis='daily', monthly_rate=Decimal('0'), daily_rate=Decimal('500'),
        days=22, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='daily', period_end=date(2026, 6, 30),
        semi_timing='second_cutoff'))
    half_month = service.compute_line(dict(
        pay_basis='daily', monthly_rate=Decimal('0'), daily_rate=Decimal('500'),
        days=11, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='daily', period_end=date(2026, 6, 30),
        semi_timing='second_cutoff'))
    assert full_month['basic_gross'] == Decimal('11000.00')   # 500*22
    assert half_month['basic_gross'] == Decimal('5500.00')    # 500*11
    # Same monthly_basis proxy (500*22) drives IDENTICAL statutory for both,
    # even though half_month's actual pay is half.
    assert full_month['statutory'] == half_month['statutory']


def test_wht_bracket_boundary_exact_semi_monthly(db_session):
    """taxable_comp exactly at a semi-monthly WHT bracket's lower bound resolves
    to that bracket -- proven through the full compute_line composition (not
    just the effective_wht_bracket lookup layer already covered above). Uses
    'first_cutoff' timing + semi_period=2 (statutory NOT applied on cutoff 2
    under first_cutoff) so gross == taxable_comp exactly, for a clean
    hand-checkable anchor."""
    seed_statutory_2026()
    line = service.compute_line(dict(
        pay_basis='monthly', monthly_rate=Decimal('33334'), days=0, hours=0,
        ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='semi_monthly', period_end=date(2026, 6, 30),
        semi_timing='first_cutoff', semi_period=2))
    assert line['gross_pay'] == Decimal('16667.00')      # 33334 / 2
    assert line['taxable_comp'] == Decimal('16667.00')   # statutory not applied on cutoff 2
    assert line['wht'] == Decimal('937.50')              # bracket 3 base_tax, zero excess
    assert line['wht_bracket_id'] is not None


def test_wht_bracket_contiguous_no_gap_via_compute_line(db_session):
    """One centavo apart, straddling a semi-monthly WHT bracket boundary,
    resolves to DIFFERENT brackets but a continuous (matching) tax amount --
    proves the brackets are gapless when composed through compute_line, not
    just at the effective_wht_bracket lookup layer. This exact class of gap
    was a real, shipped bug in Tasks 2-3 (off-by-one at a bracket boundary)."""
    seed_statutory_2026()
    common = dict(
        pay_basis='monthly', days=0, hours=0,
        ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='semi_monthly', period_end=date(2026, 6, 30),
        semi_timing='first_cutoff', semi_period=2)
    at_boundary = service.compute_line({**common, 'monthly_rate': Decimal('33334')})
    just_below = service.compute_line({**common, 'monthly_rate': Decimal('33333.98')})

    assert at_boundary['taxable_comp'] == Decimal('16667.00')
    assert just_below['taxable_comp'] == Decimal('16666.99')
    assert at_boundary['wht_bracket_id'] != just_below['wht_bracket_id']
    # Continuous at the boundary -- no jump, no gap.
    assert at_boundary['wht'] == Decimal('937.50')
    assert just_below['wht'] == Decimal('937.50')

    b_at = db.session.get(service.CompensationWHTBracket, at_boundary['wht_bracket_id'])
    b_below = db.session.get(service.CompensationWHTBracket, just_below['wht_bracket_id'])
    assert b_at.bracket_no == 3
    assert b_below.bracket_no == 2


def test_semi_monthly_second_cutoff_timing(db_session):
    """Default 'second_cutoff' timing: statutory EE deductions apply ONLY on the
    2nd semi-monthly cutoff; WHT still computes every cutoff on that cutoff's
    own taxable. The 'statutory' dict itself is always the full computed
    contribution regardless of period (compute_statutory doesn't know about
    timing) -- only the amount folded into taxable_comp/net_pay differs."""
    seed_statutory_2026()
    common = dict(
        pay_basis='monthly', monthly_rate=Decimal('40000'), days=0, hours=0,
        ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='semi_monthly', period_end=date(2026, 6, 30),
        semi_timing='second_cutoff')

    period1 = service.compute_line({**common, 'semi_period': 1})
    period2 = service.compute_line({**common, 'semi_period': 2})

    # statutory dict is identical both periods (same monthly_basis input).
    assert period1['statutory'] == period2['statutory'] == {
        'sss_msc': Decimal('40000'), 'sss_ec': Decimal('40.00'),
        'sss_ee': Decimal('2000.00'), 'sss_er': Decimal('4000.00'),
        'philhealth_ee': Decimal('1000.00'), 'philhealth_er': Decimal('1000.00'),
        'pagibig_ee': Decimal('200.00'), 'pagibig_er': Decimal('200.00'),
    }

    # Cutoff 1: statutory NOT applied -- taxable/net keep the full gross.
    assert period1['taxable_comp'] == Decimal('20000.00')
    assert period1['wht'] == Decimal('1604.10')
    assert period1['net_pay'] == Decimal('18395.90')

    # Cutoff 2: statutory applied -- taxable/net reduced by the EE deduction.
    assert period2['taxable_comp'] == Decimal('16800.00')   # 20000 - 3200 EE
    assert period2['wht'] == Decimal('964.10')
    assert period2['net_pay'] == Decimal('15835.90')


def test_semi_monthly_first_cutoff_timing(db_session):
    """'first_cutoff' timing: statutory applies ONLY on the 1st cutoff -- the
    mirror image of second_cutoff."""
    seed_statutory_2026()
    common = dict(
        pay_basis='monthly', monthly_rate=Decimal('40000'), days=0, hours=0,
        ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='semi_monthly', period_end=date(2026, 6, 30),
        semi_timing='first_cutoff')

    period1 = service.compute_line({**common, 'semi_period': 1})
    period2 = service.compute_line({**common, 'semi_period': 2})

    assert period1['taxable_comp'] == Decimal('16800.00')   # statutory applied here
    assert period2['taxable_comp'] == Decimal('20000.00')   # statutory NOT applied here


def test_semi_monthly_split_50_50_timing_applies_both_cutoffs(db_session):
    """'split_50_50' timing: statutory applies on BOTH cutoffs. Per the design
    note in _semi_applies_statutory, this flag only decides WHETHER statutory
    applies -- it does not itself halve the amount, so a full EE deduction is
    folded in on each cutoff unless the caller passes already-halved inputs
    (e.g. a halved monthly_rate) for a true 50/50 split."""
    seed_statutory_2026()
    common = dict(
        pay_basis='monthly', monthly_rate=Decimal('40000'), days=0, hours=0,
        ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        is_mwe=False, pay_frequency='semi_monthly', period_end=date(2026, 6, 30),
        semi_timing='split_50_50')

    period1 = service.compute_line({**common, 'semi_period': 1})
    period2 = service.compute_line({**common, 'semi_period': 2})

    assert period1['taxable_comp'] == Decimal('16800.00')
    assert period2['taxable_comp'] == Decimal('16800.00')
