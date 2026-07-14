"""
Seed statutory payroll master data for 2026 (SSS, PhilHealth, Pag-IBIG, TRAIN WHT).

This module populates the initial statutory tables with reference values from
current SSS/BIR circulars. Values are editable master data by design — this seed
is a starting snapshot that accountants may adjust as circulars change.
"""

from datetime import date
from decimal import Decimal
from app import db
from app.payroll.tables_models import (
    SSSContributionTable, SSSContributionRow, PhilHealthRate,
    PagIbigRate, CompensationWHTBracket)


def seed_statutory_2026():
    """Seed 2026 statutory tables (SSS, PhilHealth, Pag-IBIG, TRAIN WHT).

    Guard against double-seeding: if a 2026-effective row already exists, skip.
    """
    _seed_sss_2026()
    _seed_philhealth_2026()
    _seed_pagibig_2026()
    _seed_wht_2026()


def _seed_sss_2026():
    """Seed 2026 SSS contribution table.

    Reference: SSS Contribution Table for Calendar Year 2026
    Based on published salary brackets and contribution amounts.
    """
    effective_from = date(2026, 1, 1)

    # Check if already exists
    existing = SSSContributionTable.query.filter_by(effective_from=effective_from).first()
    if existing:
        print("  [SKIP] SSS 2026 table already exists")
        return

    tbl = SSSContributionTable(effective_from=effective_from, created_by='seed')
    db.session.add(tbl)
    db.session.flush()  # Flush to get the table ID

    # SSS 2026 contribution brackets (source: SSS official table, corrected
    # 2026-07-14 per BUG-PAYROLL-SSS-SEED-ER-RATE-INCONSISTENT). Format:
    # comp_from, comp_to, msc, ee_amount, er_amount, ee_wisp, er_wisp, ec_amount
    #
    # - MSC granularity: 500-peso increments, floor MSC 5,000 (official floor --
    #   anyone earning below 5,250 is bracketed at MSC 5,000).
    # - Regular EE/ER: flat 5% EE / 10% ER of the MSC portion up to 20,000
    #   (frozen at ee=1000.00/er=2000.00 once MSC exceeds 20,000).
    # - WISP (Workers' Investment and Savings Program): applies ONLY to the MSC
    #   portion above 20,000, also at 5% EE / 10% ER on that excess.
    # - EC (Employees' Compensation): flat 10.00 (MSC < 15,000) or 30.00
    #   (MSC >= 15,000) -- NOT a percentage.
    # Every row: ee_amount + ee_wisp == msc * 5%, er_amount + er_wisp == msc * 10%
    # (verified programmatically before commit -- see bugfix-sss-report.md).
    # The msc=30,000 row (ee=1000.00, er=2000.00, ee_wisp=500.00, er_wisp=1000.00,
    # ec=30.00) matches Task 3's already-approved anchor split exactly.
    sss_rows = [
        (Decimal('0'), Decimal('499.99'), Decimal('5000'), Decimal('250.00'), Decimal('500.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('500'), Decimal('999.99'), Decimal('5500'), Decimal('275.00'), Decimal('550.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('1000'), Decimal('1499.99'), Decimal('6000'), Decimal('300.00'), Decimal('600.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('1500'), Decimal('1999.99'), Decimal('6500'), Decimal('325.00'), Decimal('650.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('2000'), Decimal('2499.99'), Decimal('7000'), Decimal('350.00'), Decimal('700.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('2500'), Decimal('2999.99'), Decimal('7500'), Decimal('375.00'), Decimal('750.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('3000'), Decimal('3499.99'), Decimal('8000'), Decimal('400.00'), Decimal('800.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('3500'), Decimal('3999.99'), Decimal('8500'), Decimal('425.00'), Decimal('850.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('4000'), Decimal('4499.99'), Decimal('9000'), Decimal('450.00'), Decimal('900.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('4500'), Decimal('4999.99'), Decimal('9500'), Decimal('475.00'), Decimal('950.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('5000'), Decimal('5499.99'), Decimal('10000'), Decimal('500.00'), Decimal('1000.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('5500'), Decimal('5999.99'), Decimal('10500'), Decimal('525.00'), Decimal('1050.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('6000'), Decimal('6499.99'), Decimal('11000'), Decimal('550.00'), Decimal('1100.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('6500'), Decimal('6999.99'), Decimal('11500'), Decimal('575.00'), Decimal('1150.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('7000'), Decimal('7499.99'), Decimal('12000'), Decimal('600.00'), Decimal('1200.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('7500'), Decimal('7999.99'), Decimal('12500'), Decimal('625.00'), Decimal('1250.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('8000'), Decimal('8499.99'), Decimal('13000'), Decimal('650.00'), Decimal('1300.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('8500'), Decimal('8999.99'), Decimal('13500'), Decimal('675.00'), Decimal('1350.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('9000'), Decimal('9499.99'), Decimal('14000'), Decimal('700.00'), Decimal('1400.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('9500'), Decimal('9999.99'), Decimal('14500'), Decimal('725.00'), Decimal('1450.00'), Decimal('0.00'), Decimal('0.00'), Decimal('10.00')),
        (Decimal('10000'), Decimal('10499.99'), Decimal('15000'), Decimal('750.00'), Decimal('1500.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('10500'), Decimal('10999.99'), Decimal('15500'), Decimal('775.00'), Decimal('1550.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('11000'), Decimal('11499.99'), Decimal('16000'), Decimal('800.00'), Decimal('1600.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('11500'), Decimal('11999.99'), Decimal('16500'), Decimal('825.00'), Decimal('1650.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('12000'), Decimal('12499.99'), Decimal('17000'), Decimal('850.00'), Decimal('1700.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('12500'), Decimal('12999.99'), Decimal('17500'), Decimal('875.00'), Decimal('1750.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('13000'), Decimal('13499.99'), Decimal('18000'), Decimal('900.00'), Decimal('1800.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('13500'), Decimal('13999.99'), Decimal('18500'), Decimal('925.00'), Decimal('1850.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('14000'), Decimal('14499.99'), Decimal('19000'), Decimal('950.00'), Decimal('1900.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('14500'), Decimal('14999.99'), Decimal('19500'), Decimal('975.00'), Decimal('1950.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('15000'), Decimal('15499.99'), Decimal('20000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('0.00'), Decimal('0.00'), Decimal('30.00')),
        (Decimal('15500'), Decimal('15999.99'), Decimal('20500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('25.00'), Decimal('50.00'), Decimal('30.00')),
        (Decimal('16000'), Decimal('16499.99'), Decimal('21000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('50.00'), Decimal('100.00'), Decimal('30.00')),
        (Decimal('16500'), Decimal('16999.99'), Decimal('21500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('75.00'), Decimal('150.00'), Decimal('30.00')),
        (Decimal('17000'), Decimal('17499.99'), Decimal('22000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('100.00'), Decimal('200.00'), Decimal('30.00')),
        (Decimal('17500'), Decimal('17999.99'), Decimal('22500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('125.00'), Decimal('250.00'), Decimal('30.00')),
        (Decimal('18000'), Decimal('18499.99'), Decimal('23000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('150.00'), Decimal('300.00'), Decimal('30.00')),
        (Decimal('18500'), Decimal('18999.99'), Decimal('23500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('175.00'), Decimal('350.00'), Decimal('30.00')),
        (Decimal('19000'), Decimal('19499.99'), Decimal('24000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('200.00'), Decimal('400.00'), Decimal('30.00')),
        (Decimal('19500'), Decimal('19999.99'), Decimal('24500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('225.00'), Decimal('450.00'), Decimal('30.00')),
        (Decimal('20000'), Decimal('20499.99'), Decimal('25000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('250.00'), Decimal('500.00'), Decimal('30.00')),
        (Decimal('20500'), Decimal('20999.99'), Decimal('25500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('275.00'), Decimal('550.00'), Decimal('30.00')),
        (Decimal('21000'), Decimal('21499.99'), Decimal('26000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('300.00'), Decimal('600.00'), Decimal('30.00')),
        (Decimal('21500'), Decimal('21999.99'), Decimal('26500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('325.00'), Decimal('650.00'), Decimal('30.00')),
        (Decimal('22000'), Decimal('22499.99'), Decimal('27000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('350.00'), Decimal('700.00'), Decimal('30.00')),
        (Decimal('22500'), Decimal('22999.99'), Decimal('27500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('375.00'), Decimal('750.00'), Decimal('30.00')),
        (Decimal('23000'), Decimal('23499.99'), Decimal('28000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('400.00'), Decimal('800.00'), Decimal('30.00')),
        (Decimal('23500'), Decimal('23999.99'), Decimal('28500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('425.00'), Decimal('850.00'), Decimal('30.00')),
        (Decimal('24000'), Decimal('24499.99'), Decimal('29000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('450.00'), Decimal('900.00'), Decimal('30.00')),
        (Decimal('24500'), Decimal('24999.99'), Decimal('29500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('475.00'), Decimal('950.00'), Decimal('30.00')),
        (Decimal('25000'), Decimal('25499.99'), Decimal('30000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('500.00'), Decimal('1000.00'), Decimal('30.00')),
        (Decimal('25500'), Decimal('25999.99'), Decimal('30500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('525.00'), Decimal('1050.00'), Decimal('30.00')),
        (Decimal('26000'), Decimal('26499.99'), Decimal('31000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('550.00'), Decimal('1100.00'), Decimal('30.00')),
        (Decimal('26500'), Decimal('26999.99'), Decimal('31500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('575.00'), Decimal('1150.00'), Decimal('30.00')),
        (Decimal('27000'), Decimal('27499.99'), Decimal('32000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('600.00'), Decimal('1200.00'), Decimal('30.00')),
        (Decimal('27500'), Decimal('27999.99'), Decimal('32500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('625.00'), Decimal('1250.00'), Decimal('30.00')),
        (Decimal('28000'), Decimal('28499.99'), Decimal('33000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('650.00'), Decimal('1300.00'), Decimal('30.00')),
        (Decimal('28500'), Decimal('28999.99'), Decimal('33500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('675.00'), Decimal('1350.00'), Decimal('30.00')),
        (Decimal('29000'), Decimal('29499.99'), Decimal('34000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('700.00'), Decimal('1400.00'), Decimal('30.00')),
        (Decimal('29500'), Decimal('29999.99'), Decimal('34500'), Decimal('1000.00'), Decimal('2000.00'), Decimal('725.00'), Decimal('1450.00'), Decimal('30.00')),
        (Decimal('30000'), None, Decimal('35000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('750.00'), Decimal('1500.00'), Decimal('30.00')),
    ]

    for row_data in sss_rows:
        comp_from, comp_to, msc, ee_amount, er_amount, ee_wisp, er_wisp, ec_amount = row_data
        row = SSSContributionRow(
            comp_from=comp_from,
            comp_to=comp_to,
            msc=msc,
            ee_amount=ee_amount,
            er_amount=er_amount,
            ee_wisp=ee_wisp,
            er_wisp=er_wisp,
            ec_amount=ec_amount
        )
        tbl.rows.append(row)

    db.session.commit()
    print("  [OK] SSS 2026 table created")


def _seed_philhealth_2026():
    """Seed 2026 PhilHealth premium rate (5%, floor 10k, ceiling 100k, 50/50 split)."""
    effective_from = date(2026, 1, 1)

    existing = PhilHealthRate.query.filter_by(effective_from=effective_from).first()
    if existing:
        print("  [SKIP] PhilHealth 2026 rate already exists")
        return

    rate = PhilHealthRate(
        premium_rate=Decimal('0.0500'),
        income_floor=Decimal('10000'),
        income_ceiling=Decimal('100000'),
        ee_share=Decimal('0.5000'),
        effective_from=effective_from,
        created_by='seed'
    )
    db.session.add(rate)
    db.session.commit()
    print("  [OK] PhilHealth 2026 rate created")


def _seed_pagibig_2026():
    """Seed 2026 Pag-IBIG rate (threshold 1500, rates 1%-2%, ER 2%, ceiling 10k)."""
    effective_from = date(2026, 1, 1)

    existing = PagIbigRate.query.filter_by(effective_from=effective_from).first()
    if existing:
        print("  [SKIP] Pag-IBIG 2026 rate already exists")
        return

    rate = PagIbigRate(
        bracket_threshold=Decimal('1500'),
        lower_ee_rate=Decimal('0.01'),
        upper_ee_rate=Decimal('0.02'),
        er_rate=Decimal('0.02'),
        mc_ceiling=Decimal('10000'),
        effective_from=effective_from,
        created_by='seed'
    )
    db.session.add(rate)
    db.session.commit()
    print("  [OK] Pag-IBIG 2026 rate created")


def _seed_wht_2026():
    """Seed 2026 TRAIN compensation WHT brackets for all frequencies.

    The TRAIN law publishes monthly brackets, which are then converted for other
    pay frequencies by pro-rating.

    Monthly 2026 brackets (BIR-published thresholds: 20,833 / 33,333 / 66,667):
    - Bracket 1: 0 - 20832, base 0, rate 0%
    - Bracket 2: 20833 - 33332, base 0, rate 15%
    - Bracket 3: 33333 - 66666, base 1875, rate 20%
    - Bracket 4: 66667+, base 8541.8, rate 25%

    Brackets are contiguous with NO gap: every bracket's upper_bound is
    exactly one CENT (0.01) less than the next bracket's lower_bound, so that
    effective_wht_bracket's `taxable >= lower and taxable <= upper` predicate
    matches every Decimal value (including fractional-peso taxable amounts)
    with no fall-through -- the same non-overlapping, gapless ".99-style"
    pattern already used for the SSS contribution table above. Lower bounds
    anchor on the whole-peso official BIR thresholds (20,833 / 33,333 /
    66,667 for monthly; matches the design anchor: bracket 2 = lower 20833 /
    bracket 3 starts at 33333) or their pro-rated equivalents for the other
    frequencies. An earlier draft of this fix used whole-peso ("minus 1")
    upper bounds for monthly only -- that reintroduced a 99-cent gap at every
    transition (e.g. 20832.01-20832.99 matched no bracket), so monthly now
    uses the same cents-precision upper bounds as the other three frequencies.

    Semi-monthly = monthly / 2
    Weekly = monthly / 4.333 (52 weeks / 12 months)
    Daily = monthly / 20.833 (260 working days / 12.5 pay periods per year)
    """
    effective_from = date(2026, 1, 1)

    # Check if already exists for any frequency
    existing = CompensationWHTBracket.query.filter_by(effective_from=effective_from).first()
    if existing:
        print("  [SKIP] TRAIN 2026 brackets already exist")
        return

    # Define brackets per frequency: (frequency, bracket_no, lower, upper, base_tax, rate)
    # Monthly brackets as published by BIR (thresholds 20,833 / 33,333 / 66,667):
    # Bracket 1: 0-20832 @ 0% | Bracket 2: 20833-33332 @ 15% | Bracket 3: 33333-66666 @ 20% | Bracket 4: 66667+ @ 25%

    brackets_data = [
        # Monthly (published brackets; cents-precision contiguous, upper = next lower - 0.01)
        ('monthly', 1, Decimal('0'), Decimal('20832.99'), Decimal('0'), Decimal('0.00')),
        ('monthly', 2, Decimal('20833'), Decimal('33332.99'), Decimal('0'), Decimal('0.15')),
        ('monthly', 3, Decimal('33333'), Decimal('66666.99'), Decimal('1875'), Decimal('0.20')),
        ('monthly', 4, Decimal('66667'), None, Decimal('8541.80'), Decimal('0.25')),

        # Semi-monthly (monthly / 2); cents-precision contiguous, upper = next lower - 0.01
        ('semi_monthly', 1, Decimal('0'), Decimal('10416.99'), Decimal('0'), Decimal('0.00')),
        ('semi_monthly', 2, Decimal('10417'), Decimal('16666.99'), Decimal('0'), Decimal('0.15')),
        ('semi_monthly', 3, Decimal('16667'), Decimal('33333.99'), Decimal('937.50'), Decimal('0.20')),
        ('semi_monthly', 4, Decimal('33334'), None, Decimal('4270.90'), Decimal('0.25')),

        # Weekly (monthly * 12 / 52 = monthly / 4.333); cents-precision contiguous
        ('weekly', 1, Decimal('0'), Decimal('4808.99'), Decimal('0'), Decimal('0.00')),
        ('weekly', 2, Decimal('4809'), Decimal('7692.99'), Decimal('0'), Decimal('0.15')),
        ('weekly', 3, Decimal('7693'), Decimal('15384.99'), Decimal('432.69'), Decimal('0.20')),
        ('weekly', 4, Decimal('15385'), None, Decimal('1971.11'), Decimal('0.25')),

        # Daily (monthly * 12 / 260 = monthly / 20.833); cents-precision contiguous
        ('daily', 1, Decimal('0'), Decimal('1000.99'), Decimal('0'), Decimal('0.00')),
        ('daily', 2, Decimal('1001'), Decimal('1600.99'), Decimal('0'), Decimal('0.15')),
        ('daily', 3, Decimal('1601'), Decimal('3200.99'), Decimal('90'), Decimal('0.20')),
        ('daily', 4, Decimal('3201'), None, Decimal('410'), Decimal('0.25')),
    ]

    for freq, bracket_no, lower, upper, base_tax, rate in brackets_data:
        bracket = CompensationWHTBracket(
            frequency=freq,
            bracket_no=bracket_no,
            lower_bound=lower,
            upper_bound=upper,
            base_tax=base_tax,
            rate_on_excess=rate,
            effective_from=effective_from,
            created_by='seed'
        )
        db.session.add(bracket)

    db.session.commit()
    print("  [OK] TRAIN 2026 brackets created (daily, weekly, semi_monthly, monthly)")
