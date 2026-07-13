"""
Test payroll statutory master models (SSS, PhilHealth, Pag-IBIG, Compensation WHT).
"""

from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.payroll import service
from app.payroll.tables_models import (
    SSSContributionTable, SSSContributionRow, PhilHealthRate,
    PagIbigRate, CompensationWHTBracket, StatutoryTableChangeRequest,
)
from app.seeds.statutory_2026 import seed_statutory_2026


def test_sss_table_has_rows_and_effectivity(db_session):
    """SSS contribution table can hold salary bracket rows."""
    tbl = SSSContributionTable(effective_from=date(2026, 1, 1))
    db.session.add(tbl)
    db.session.flush()

    tbl.rows.append(SSSContributionRow(
        comp_from=Decimal('29750'), comp_to=Decimal('30249.99'),
        msc=Decimal('30000'), ee_amount=Decimal('1350'), er_amount=Decimal('2650'),
        ee_wisp=Decimal('150'), er_wisp=Decimal('350'), ec_amount=Decimal('30')))
    db.session.commit()

    assert tbl.effective_to is None
    assert tbl.rows[0].msc == Decimal('30000')


def test_wht_bracket_is_per_frequency(db_session):
    """Compensation WHT bracket has frequency and bracket number."""
    b = CompensationWHTBracket(
        frequency='monthly', bracket_no=2,
        lower_bound=Decimal('20833'), upper_bound=Decimal('33332'),
        base_tax=Decimal('0'), rate_on_excess=Decimal('0.15'),
        effective_from=date(2026, 1, 1))
    db.session.add(b)
    db.session.commit()

    assert b.frequency == 'monthly'
    assert b.bracket_no == 2


def test_philhealth_rate_has_income_bounds(db_session):
    """PhilHealth rate table has income floor/ceiling and ee share."""
    rate = PhilHealthRate(
        premium_rate=Decimal('0.0500'),
        income_floor=Decimal('10000'),
        income_ceiling=Decimal('100000'),
        ee_share=Decimal('0.5000'),
        effective_from=date(2026, 1, 1))
    db.session.add(rate)
    db.session.commit()

    assert rate.premium_rate == Decimal('0.0500')
    assert rate.ee_share == Decimal('0.5000')


def test_pagibig_rate_has_threshold_and_ceiling(db_session):
    """Pag-IBIG rate has bracket threshold and monthly comp ceiling."""
    rate = PagIbigRate(
        bracket_threshold=Decimal('5000'),
        lower_ee_rate=Decimal('0.01'),
        upper_ee_rate=Decimal('0.02'),
        er_rate=Decimal('0.02'),
        mc_ceiling=Decimal('10000'),
        effective_from=date(2026, 1, 1))
    db.session.add(rate)
    db.session.commit()

    assert rate.bracket_threshold == Decimal('5000')
    assert rate.mc_ceiling == Decimal('10000')


def test_statutory_change_request_workflow(db_session):
    """StatutoryTableChangeRequest can track approval workflow."""
    from app.users.models import User

    requester = User(username='test_user', email='test@example.com', full_name='Test User',
                     role='accountant', is_active=True)
    requester.set_password('test123')
    db.session.add(requester)
    db.session.flush()

    req = StatutoryTableChangeRequest(
        table_type='sss',
        action='create',
        status='pending',
        proposed_data='{"effective_from": "2026-01-01"}',
        request_reason='Update for 2026',
        requested_by_id=requester.id)
    db.session.add(req)
    db.session.commit()

    assert req.status == 'pending'
    assert req.action == 'create'


def test_sss_row_nullable_upper_bracket(db_session):
    """SSS contribution row can have nullable comp_to (open-ended top bracket)."""
    tbl = SSSContributionTable(effective_from=date(2026, 1, 1))
    db.session.add(tbl)
    db.session.flush()

    # Top bracket row has no upper bound
    tbl.rows.append(SSSContributionRow(
        comp_from=Decimal('50000'),
        comp_to=None,  # Open-ended
        msc=Decimal('50000'), ee_amount=Decimal('1500'), er_amount=Decimal('3500'),
        ee_wisp=Decimal('200'), er_wisp=Decimal('400'), ec_amount=Decimal('30')))
    db.session.commit()

    top_row = tbl.rows[0]
    assert top_row.comp_to is None
    assert top_row.comp_from == Decimal('50000')


def test_wht_bracket_nullable_upper_bound(db_session):
    """Compensation WHT bracket can have nullable upper_bound (open-ended)."""
    b = CompensationWHTBracket(
        frequency='monthly', bracket_no=5,
        lower_bound=Decimal('833332'),
        upper_bound=None,  # Open-ended top bracket
        base_tax=Decimal('100000'), rate_on_excess=Decimal('0.35'),
        effective_from=date(2026, 1, 1))
    db.session.add(b)
    db.session.commit()

    assert b.upper_bound is None
    assert b.lower_bound == Decimal('833332')


def test_effective_to_nullable_for_active_rates(db_session):
    """All rate tables can have nullable effective_to (indicating still active)."""
    sss = SSSContributionTable(effective_from=date(2026, 1, 1), effective_to=None)
    ph = PhilHealthRate(
        premium_rate=Decimal('0.05'), income_floor=Decimal('10000'),
        income_ceiling=Decimal('100000'), ee_share=Decimal('0.5'),
        effective_from=date(2026, 1, 1), effective_to=None)
    pagibig = PagIbigRate(
        bracket_threshold=Decimal('5000'), lower_ee_rate=Decimal('0.01'),
        upper_ee_rate=Decimal('0.02'), er_rate=Decimal('0.02'),
        mc_ceiling=Decimal('10000'),
        effective_from=date(2026, 1, 1), effective_to=None)

    db.session.add_all([sss, ph, pagibig])
    db.session.commit()

    assert sss.effective_to is None
    assert ph.effective_to is None
    assert pagibig.effective_to is None


# ---------------------------------------------------------------------------
# BUG-PAYROLL-SSS-SEED-ER-RATE-INCONSISTENT -- corrected SSS 2026 seed table.
#
# The seed had three bugs: (1) wrong bracket granularity (250-peso increments
# from MSC 1,250 instead of the real 500-peso increments from the official
# MSC 5,000 floor), (2) er_amount+er_wisp summed to only ~4% of MSC on every
# row except the already-fixed 30k anchor (real ER rate is a flat 10%, with
# WISP applying only to the MSC portion above 20,000), and (3) ec_amount was
# proportional (~0.1% of MSC) instead of the real flat 10.00/30.00 fee. This
# section pins the corrected table via a helper that finds a seeded row by
# its exact MSC value (rows are ordered by comp_from, so an MSC lookup is a
# simple linear scan -- distinct from sss_row_for, which looks up by monthly
# compensation).
# ---------------------------------------------------------------------------

def _row_by_msc(tbl, msc):
    """Find the seeded SSSContributionRow with the given exact MSC value."""
    for r in tbl.rows:
        if r.msc == msc:
            return r
    raise AssertionError(f"No seeded SSS row with msc={msc}")


def test_sss_wisp_boundary_ee_wisp_matches_corrected_seed(db_session):
    """Spot-check at the WISP boundary (MSC 20,500): ee_wisp must be 25.00 --
    this is the RED/GREEN anchor assertion for the bug fix. Against the
    ORIGINAL buggy seed this row didn't exist at all (old granularity was
    250-peso increments off a 1,250 floor, not 500-peso off a 5,000 floor),
    so this assertion fails closed (AssertionError from _row_by_msc) against
    the pre-fix seed and passes only once the corrected table is in place."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))
    row = _row_by_msc(tbl, Decimal('20500'))
    assert row.ee_wisp == Decimal('25.00')


def test_sss_floor_row_matches_corrected_seed(db_session):
    """Floor row (MSC 5,000): flat amounts, zero WISP, EC 10.00."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))
    row = _row_by_msc(tbl, Decimal('5000'))
    assert row.ee_amount == Decimal('250.00')
    assert row.er_amount == Decimal('500.00')
    assert row.ee_wisp == Decimal('0.00')
    assert row.er_wisp == Decimal('0.00')
    assert row.ec_amount == Decimal('10.00')


def test_sss_ec_threshold_matches_corrected_seed(db_session):
    """EC is a flat fee, not a percentage: 10.00 below MSC 15,000, 30.00 at
    and above it."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))
    assert _row_by_msc(tbl, Decimal('14500')).ec_amount == Decimal('10.00')
    assert _row_by_msc(tbl, Decimal('15000')).ec_amount == Decimal('30.00')


def test_sss_wisp_threshold_matches_corrected_seed(db_session):
    """WISP is zero at and below MSC 20,000, and kicks in above it."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))
    at_20000 = _row_by_msc(tbl, Decimal('20000'))
    assert at_20000.ee_wisp == Decimal('0.00')
    assert at_20000.er_wisp == Decimal('0.00')

    at_20500 = _row_by_msc(tbl, Decimal('20500'))
    assert at_20500.ee_wisp == Decimal('25.00')
    assert at_20500.er_wisp == Decimal('50.00')


def test_sss_30k_anchor_unchanged_by_corrected_seed(db_session):
    """The MSC 30,000 row (Task 3's already-approved anchor) must be
    UNCHANGED by this fix: regular EE/ER frozen at the MSC-20,000 level, WISP
    computed on the 10,000 excess above 20,000."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))
    row = _row_by_msc(tbl, Decimal('30000'))
    assert row.ee_amount == Decimal('1000.00')
    assert row.er_amount == Decimal('2000.00')
    assert row.ee_wisp == Decimal('500.00')
    assert row.er_wisp == Decimal('1000.00')
    assert row.ec_amount == Decimal('30.00')


def test_sss_ceiling_open_bracket_matches_corrected_seed(db_session):
    """A compensation of 40,000 (above every bracket) resolves via
    sss_row_for's open-bracket fallback to the MSC-35,000 ceiling row."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))
    row = service.sss_row_for(tbl, Decimal('40000'))
    assert row.comp_to is None
    assert row.msc == Decimal('35000')
    assert row.ee_amount + row.ee_wisp == Decimal('1750.00')
    assert row.er_amount + row.er_wisp == Decimal('3500.00')


def test_sss_every_row_ee_is_5pct_er_is_10pct_of_msc(db_session):
    """Comprehensive invariant: for every seeded row, ee_amount+ee_wisp is
    exactly 5% of msc and er_amount+er_wisp is exactly 10% of msc -- this is
    the exact property that was broken before the fix (er totaled ~4%)."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))
    assert len(tbl.rows) == 61
    for row in tbl.rows:
        expected_ee = (row.msc * Decimal('0.05')).quantize(Decimal('0.01'))
        expected_er = (row.msc * Decimal('0.10')).quantize(Decimal('0.01'))
        assert row.ee_amount + row.ee_wisp == expected_ee, (
            f"msc={row.msc}: ee total {row.ee_amount + row.ee_wisp} != 5% ({expected_ee})")
        assert row.er_amount + row.er_wisp == expected_er, (
            f"msc={row.msc}: er total {row.er_amount + row.er_wisp} != 10% ({expected_er})")


def test_sss_brackets_contiguous_no_gap_or_overlap(db_session):
    """Rows sorted by comp_from: each row's comp_from equals the previous
    row's comp_to + 0.01 (except the first row); the last row's comp_to is
    None (open-ended top bracket)."""
    seed_statutory_2026()
    tbl = service.effective_sss(date(2026, 6, 30))
    rows = list(tbl.rows)  # already ordered by comp_from (relationship order_by)

    for i in range(1, len(rows)):
        prev_row, row = rows[i - 1], rows[i]
        assert prev_row.comp_to is not None, (
            f"row {i - 1} (comp_from={prev_row.comp_from}) has comp_to=None but is not the last row")
        assert row.comp_from == prev_row.comp_to + Decimal('0.01'), (
            f"gap/overlap between row {i - 1} (comp_to={prev_row.comp_to}) "
            f"and row {i} (comp_from={row.comp_from})")

    assert rows[-1].comp_to is None
