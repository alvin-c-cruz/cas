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

    # SSS 2026 contribution brackets (source: SSS official table)
    # Format: comp_from, comp_to, msc, ee_amount, er_amount, ee_wisp, er_wisp, ec_amount
    sss_rows = [
        # Lower brackets
        (Decimal('1000'), Decimal('1249.99'), Decimal('1250'), Decimal('56.25'), Decimal('43.75'), Decimal('6.25'), Decimal('6.25'), Decimal('1.25')),
        (Decimal('1250'), Decimal('1499.99'), Decimal('1500'), Decimal('67.50'), Decimal('52.50'), Decimal('7.50'), Decimal('7.50'), Decimal('1.50')),
        (Decimal('1500'), Decimal('1749.99'), Decimal('1750'), Decimal('78.75'), Decimal('61.25'), Decimal('8.75'), Decimal('8.75'), Decimal('1.75')),
        (Decimal('1750'), Decimal('1999.99'), Decimal('2000'), Decimal('90.00'), Decimal('70.00'), Decimal('10.00'), Decimal('10.00'), Decimal('2.00')),
        (Decimal('2000'), Decimal('2249.99'), Decimal('2250'), Decimal('101.25'), Decimal('78.75'), Decimal('11.25'), Decimal('11.25'), Decimal('2.25')),
        (Decimal('2250'), Decimal('2499.99'), Decimal('2500'), Decimal('112.50'), Decimal('87.50'), Decimal('12.50'), Decimal('12.50'), Decimal('2.50')),
        (Decimal('2500'), Decimal('2749.99'), Decimal('2750'), Decimal('123.75'), Decimal('96.25'), Decimal('13.75'), Decimal('13.75'), Decimal('2.75')),
        (Decimal('2750'), Decimal('2999.99'), Decimal('3000'), Decimal('135.00'), Decimal('105.00'), Decimal('15.00'), Decimal('15.00'), Decimal('3.00')),
        (Decimal('3000'), Decimal('3249.99'), Decimal('3250'), Decimal('146.25'), Decimal('113.75'), Decimal('16.25'), Decimal('16.25'), Decimal('3.25')),
        (Decimal('3250'), Decimal('3499.99'), Decimal('3500'), Decimal('157.50'), Decimal('122.50'), Decimal('17.50'), Decimal('17.50'), Decimal('3.50')),
        (Decimal('3500'), Decimal('3749.99'), Decimal('3750'), Decimal('168.75'), Decimal('131.25'), Decimal('18.75'), Decimal('18.75'), Decimal('3.75')),
        (Decimal('3750'), Decimal('3999.99'), Decimal('4000'), Decimal('180.00'), Decimal('140.00'), Decimal('20.00'), Decimal('20.00'), Decimal('4.00')),
        (Decimal('4000'), Decimal('4249.99'), Decimal('4250'), Decimal('191.25'), Decimal('148.75'), Decimal('21.25'), Decimal('21.25'), Decimal('4.25')),
        (Decimal('4250'), Decimal('4499.99'), Decimal('4500'), Decimal('202.50'), Decimal('157.50'), Decimal('22.50'), Decimal('22.50'), Decimal('4.50')),
        (Decimal('4500'), Decimal('4749.99'), Decimal('4750'), Decimal('213.75'), Decimal('166.25'), Decimal('23.75'), Decimal('23.75'), Decimal('4.75')),
        (Decimal('4750'), Decimal('4999.99'), Decimal('5000'), Decimal('225.00'), Decimal('175.00'), Decimal('25.00'), Decimal('25.00'), Decimal('5.00')),
        (Decimal('5000'), Decimal('5249.99'), Decimal('5250'), Decimal('236.25'), Decimal('183.75'), Decimal('26.25'), Decimal('26.25'), Decimal('5.25')),
        (Decimal('5250'), Decimal('5499.99'), Decimal('5500'), Decimal('247.50'), Decimal('192.50'), Decimal('27.50'), Decimal('27.50'), Decimal('5.50')),
        (Decimal('5500'), Decimal('5749.99'), Decimal('5750'), Decimal('258.75'), Decimal('201.25'), Decimal('28.75'), Decimal('28.75'), Decimal('5.75')),
        (Decimal('5750'), Decimal('5999.99'), Decimal('6000'), Decimal('270.00'), Decimal('210.00'), Decimal('30.00'), Decimal('30.00'), Decimal('6.00')),
        (Decimal('6000'), Decimal('6249.99'), Decimal('6250'), Decimal('281.25'), Decimal('218.75'), Decimal('31.25'), Decimal('31.25'), Decimal('6.25')),
        (Decimal('6250'), Decimal('6499.99'), Decimal('6500'), Decimal('292.50'), Decimal('227.50'), Decimal('32.50'), Decimal('32.50'), Decimal('6.50')),
        (Decimal('6500'), Decimal('6749.99'), Decimal('6750'), Decimal('303.75'), Decimal('236.25'), Decimal('33.75'), Decimal('33.75'), Decimal('6.75')),
        (Decimal('6750'), Decimal('6999.99'), Decimal('7000'), Decimal('315.00'), Decimal('245.00'), Decimal('35.00'), Decimal('35.00'), Decimal('7.00')),
        (Decimal('7000'), Decimal('7249.99'), Decimal('7250'), Decimal('326.25'), Decimal('253.75'), Decimal('36.25'), Decimal('36.25'), Decimal('7.25')),
        (Decimal('7250'), Decimal('7499.99'), Decimal('7500'), Decimal('337.50'), Decimal('262.50'), Decimal('37.50'), Decimal('37.50'), Decimal('7.50')),
        (Decimal('7500'), Decimal('7749.99'), Decimal('7750'), Decimal('348.75'), Decimal('271.25'), Decimal('38.75'), Decimal('38.75'), Decimal('7.75')),
        (Decimal('7750'), Decimal('7999.99'), Decimal('8000'), Decimal('360.00'), Decimal('280.00'), Decimal('40.00'), Decimal('40.00'), Decimal('8.00')),
        (Decimal('8000'), Decimal('8249.99'), Decimal('8250'), Decimal('371.25'), Decimal('288.75'), Decimal('41.25'), Decimal('41.25'), Decimal('8.25')),
        (Decimal('8250'), Decimal('8499.99'), Decimal('8500'), Decimal('382.50'), Decimal('297.50'), Decimal('42.50'), Decimal('42.50'), Decimal('8.50')),
        (Decimal('8500'), Decimal('8749.99'), Decimal('8750'), Decimal('393.75'), Decimal('306.25'), Decimal('43.75'), Decimal('43.75'), Decimal('8.75')),
        (Decimal('8750'), Decimal('8999.99'), Decimal('9000'), Decimal('405.00'), Decimal('315.00'), Decimal('45.00'), Decimal('45.00'), Decimal('9.00')),
        (Decimal('9000'), Decimal('9249.99'), Decimal('9250'), Decimal('416.25'), Decimal('323.75'), Decimal('46.25'), Decimal('46.25'), Decimal('9.25')),
        (Decimal('9250'), Decimal('9499.99'), Decimal('9500'), Decimal('427.50'), Decimal('332.50'), Decimal('47.50'), Decimal('47.50'), Decimal('9.50')),
        (Decimal('9500'), Decimal('9749.99'), Decimal('9750'), Decimal('438.75'), Decimal('341.25'), Decimal('48.75'), Decimal('48.75'), Decimal('9.75')),
        (Decimal('9750'), Decimal('9999.99'), Decimal('10000'), Decimal('450.00'), Decimal('350.00'), Decimal('50.00'), Decimal('50.00'), Decimal('10.00')),
        (Decimal('10000'), Decimal('10249.99'), Decimal('10250'), Decimal('461.25'), Decimal('358.75'), Decimal('51.25'), Decimal('51.25'), Decimal('10.25')),
        (Decimal('10250'), Decimal('10499.99'), Decimal('10500'), Decimal('472.50'), Decimal('367.50'), Decimal('52.50'), Decimal('52.50'), Decimal('10.50')),
        (Decimal('10500'), Decimal('10749.99'), Decimal('10750'), Decimal('483.75'), Decimal('376.25'), Decimal('53.75'), Decimal('53.75'), Decimal('10.75')),
        (Decimal('10750'), Decimal('10999.99'), Decimal('11000'), Decimal('495.00'), Decimal('385.00'), Decimal('55.00'), Decimal('55.00'), Decimal('11.00')),
        (Decimal('11000'), Decimal('11249.99'), Decimal('11250'), Decimal('506.25'), Decimal('393.75'), Decimal('56.25'), Decimal('56.25'), Decimal('11.25')),
        (Decimal('11250'), Decimal('11499.99'), Decimal('11500'), Decimal('517.50'), Decimal('402.50'), Decimal('57.50'), Decimal('57.50'), Decimal('11.50')),
        (Decimal('11500'), Decimal('11749.99'), Decimal('11750'), Decimal('528.75'), Decimal('411.25'), Decimal('58.75'), Decimal('58.75'), Decimal('11.75')),
        (Decimal('11750'), Decimal('11999.99'), Decimal('12000'), Decimal('540.00'), Decimal('420.00'), Decimal('60.00'), Decimal('60.00'), Decimal('12.00')),
        (Decimal('12000'), Decimal('12249.99'), Decimal('12250'), Decimal('551.25'), Decimal('428.75'), Decimal('61.25'), Decimal('61.25'), Decimal('12.25')),
        (Decimal('12250'), Decimal('12499.99'), Decimal('12500'), Decimal('562.50'), Decimal('437.50'), Decimal('62.50'), Decimal('62.50'), Decimal('12.50')),
        (Decimal('12500'), Decimal('12749.99'), Decimal('12750'), Decimal('573.75'), Decimal('446.25'), Decimal('63.75'), Decimal('63.75'), Decimal('12.75')),
        (Decimal('12750'), Decimal('12999.99'), Decimal('13000'), Decimal('585.00'), Decimal('455.00'), Decimal('65.00'), Decimal('65.00'), Decimal('13.00')),
        (Decimal('13000'), Decimal('13249.99'), Decimal('13250'), Decimal('596.25'), Decimal('463.75'), Decimal('66.25'), Decimal('66.25'), Decimal('13.25')),
        (Decimal('13250'), Decimal('13499.99'), Decimal('13500'), Decimal('607.50'), Decimal('472.50'), Decimal('67.50'), Decimal('67.50'), Decimal('13.50')),
        (Decimal('13500'), Decimal('13749.99'), Decimal('13750'), Decimal('618.75'), Decimal('481.25'), Decimal('68.75'), Decimal('68.75'), Decimal('13.75')),
        (Decimal('13750'), Decimal('13999.99'), Decimal('14000'), Decimal('630.00'), Decimal('490.00'), Decimal('70.00'), Decimal('70.00'), Decimal('14.00')),
        (Decimal('14000'), Decimal('14249.99'), Decimal('14250'), Decimal('641.25'), Decimal('498.75'), Decimal('71.25'), Decimal('71.25'), Decimal('14.25')),
        (Decimal('14250'), Decimal('14499.99'), Decimal('14500'), Decimal('652.50'), Decimal('507.50'), Decimal('72.50'), Decimal('72.50'), Decimal('14.50')),
        (Decimal('14500'), Decimal('14749.99'), Decimal('14750'), Decimal('663.75'), Decimal('516.25'), Decimal('73.75'), Decimal('73.75'), Decimal('14.75')),
        (Decimal('14750'), Decimal('14999.99'), Decimal('15000'), Decimal('675.00'), Decimal('525.00'), Decimal('75.00'), Decimal('75.00'), Decimal('15.00')),
        (Decimal('15000'), Decimal('15249.99'), Decimal('15250'), Decimal('686.25'), Decimal('533.75'), Decimal('76.25'), Decimal('76.25'), Decimal('15.25')),
        (Decimal('15250'), Decimal('15499.99'), Decimal('15500'), Decimal('697.50'), Decimal('542.50'), Decimal('77.50'), Decimal('77.50'), Decimal('15.50')),
        (Decimal('15500'), Decimal('15749.99'), Decimal('15750'), Decimal('708.75'), Decimal('551.25'), Decimal('78.75'), Decimal('78.75'), Decimal('15.75')),
        (Decimal('15750'), Decimal('15999.99'), Decimal('16000'), Decimal('720.00'), Decimal('560.00'), Decimal('80.00'), Decimal('80.00'), Decimal('16.00')),
        (Decimal('16000'), Decimal('16249.99'), Decimal('16250'), Decimal('731.25'), Decimal('568.75'), Decimal('81.25'), Decimal('81.25'), Decimal('16.25')),
        (Decimal('16250'), Decimal('16499.99'), Decimal('16500'), Decimal('742.50'), Decimal('577.50'), Decimal('82.50'), Decimal('82.50'), Decimal('16.50')),
        (Decimal('16500'), Decimal('16749.99'), Decimal('16750'), Decimal('753.75'), Decimal('586.25'), Decimal('83.75'), Decimal('83.75'), Decimal('16.75')),
        (Decimal('16750'), Decimal('16999.99'), Decimal('17000'), Decimal('765.00'), Decimal('595.00'), Decimal('85.00'), Decimal('85.00'), Decimal('17.00')),
        (Decimal('17000'), Decimal('17249.99'), Decimal('17250'), Decimal('776.25'), Decimal('603.75'), Decimal('86.25'), Decimal('86.25'), Decimal('17.25')),
        (Decimal('17250'), Decimal('17499.99'), Decimal('17500'), Decimal('787.50'), Decimal('612.50'), Decimal('87.50'), Decimal('87.50'), Decimal('17.50')),
        (Decimal('17500'), Decimal('17749.99'), Decimal('17750'), Decimal('798.75'), Decimal('621.25'), Decimal('88.75'), Decimal('88.75'), Decimal('17.75')),
        (Decimal('17750'), Decimal('17999.99'), Decimal('18000'), Decimal('810.00'), Decimal('630.00'), Decimal('90.00'), Decimal('90.00'), Decimal('18.00')),
        (Decimal('18000'), Decimal('18249.99'), Decimal('18250'), Decimal('821.25'), Decimal('638.75'), Decimal('91.25'), Decimal('91.25'), Decimal('18.25')),
        (Decimal('18250'), Decimal('18499.99'), Decimal('18500'), Decimal('832.50'), Decimal('647.50'), Decimal('92.50'), Decimal('92.50'), Decimal('18.50')),
        (Decimal('18500'), Decimal('18749.99'), Decimal('18750'), Decimal('843.75'), Decimal('656.25'), Decimal('93.75'), Decimal('93.75'), Decimal('18.75')),
        (Decimal('18750'), Decimal('18999.99'), Decimal('19000'), Decimal('855.00'), Decimal('665.00'), Decimal('95.00'), Decimal('95.00'), Decimal('19.00')),
        (Decimal('19000'), Decimal('19249.99'), Decimal('19250'), Decimal('866.25'), Decimal('673.75'), Decimal('96.25'), Decimal('96.25'), Decimal('19.25')),
        (Decimal('19250'), Decimal('19499.99'), Decimal('19500'), Decimal('877.50'), Decimal('682.50'), Decimal('97.50'), Decimal('97.50'), Decimal('19.50')),
        (Decimal('19500'), Decimal('19749.99'), Decimal('19750'), Decimal('888.75'), Decimal('691.25'), Decimal('98.75'), Decimal('98.75'), Decimal('19.75')),
        (Decimal('19750'), Decimal('19999.99'), Decimal('20000'), Decimal('900.00'), Decimal('700.00'), Decimal('100.00'), Decimal('100.00'), Decimal('20.00')),
        (Decimal('20000'), Decimal('20249.99'), Decimal('20250'), Decimal('911.25'), Decimal('708.75'), Decimal('101.25'), Decimal('101.25'), Decimal('20.25')),
        (Decimal('20250'), Decimal('20499.99'), Decimal('20500'), Decimal('922.50'), Decimal('717.50'), Decimal('102.50'), Decimal('102.50'), Decimal('20.50')),
        (Decimal('20500'), Decimal('20749.99'), Decimal('20750'), Decimal('933.75'), Decimal('726.25'), Decimal('103.75'), Decimal('103.75'), Decimal('20.75')),
        (Decimal('20750'), Decimal('20999.99'), Decimal('21000'), Decimal('945.00'), Decimal('735.00'), Decimal('105.00'), Decimal('105.00'), Decimal('21.00')),
        (Decimal('21000'), Decimal('29749.99'), Decimal('25000'), Decimal('1125.00'), Decimal('875.00'), Decimal('125.00'), Decimal('125.00'), Decimal('25.00')),
        # The critical ₱30k bracket (test anchor point). Regular MSC capped at
        # 20,000 (EE 5% = 1000, ER 10% = 2000) + WISP on the 10,000 excess up
        # to 30,000 (EE 5% = 500, ER 10% = 1000). Totals: EE 1500 (5%), ER 3000
        # (10%) -- matches the published circular split. A prior version of
        # this row had er_amount/er_wisp totaling 3300.00 (an 11% ER rate) --
        # an arithmetic bug found while implementing compute_statutory's
        # anchor test (Task 3); fixed here together with the seed.
        (Decimal('29750'), Decimal('39999.99'), Decimal('30000'), Decimal('1000.00'), Decimal('2000.00'), Decimal('500.00'), Decimal('1000.00'), Decimal('30.00')),
        # Top open bracket
        (Decimal('40000'), None, Decimal('40000'), Decimal('1800.00'), Decimal('3200.00'), Decimal('200.00'), Decimal('800.00'), Decimal('40.00')),
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
