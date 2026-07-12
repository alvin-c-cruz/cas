"""
Test payroll statutory master models (SSS, PhilHealth, Pag-IBIG, Compensation WHT).
"""

from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.payroll.tables_models import (
    SSSContributionTable, SSSContributionRow, PhilHealthRate,
    PagIbigRate, CompensationWHTBracket, StatutoryTableChangeRequest,
)


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
