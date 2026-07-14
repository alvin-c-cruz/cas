"""post_payroll_je: the accrual JE engine that builds a balanced posting from
a PayrollRun's header total_* buckets, with the 20501 (Accrued Salaries) net-
pay leg as a GUARDED plug -- asserted equal to run.total_net_pay, never
silently absorbed (posted-je-leg-vs-source-header-invariant).
"""
from decimal import Decimal

import pytest

from app.payroll import service

pytestmark = [pytest.mark.integration]


def test_je_ties_and_plug_equals_net(app_ctx, posted_run_factory):
    run = posted_run_factory()   # 1+ lines, control accts assigned
    je = service.post_payroll_je(run)
    assert je.is_balanced
    plug = next(l for l in je.lines if l.account.code == '20501')
    assert plug.credit_amount == run.total_net_pay
    # every non-plug leg equals its header bucket
    dr_sal = next(l for l in je.lines if l.account.code == '50210')
    assert dr_sal.debit_amount == run.total_gross


def test_plug_guard_raises_on_bucket_mismatch(app_ctx, posted_run_factory, monkeypatch):
    run = posted_run_factory()
    run.total_net_pay = run.total_net_pay + Decimal('1.00')   # corrupt the header
    with pytest.raises(ValueError, match="net pay"):
        service.post_payroll_je(run)


def test_unassigned_control_account_is_friendly(app_ctx, run_factory):
    run = run_factory()   # control accounts NOT assigned
    with pytest.raises(service.ControlAccountError):
        service.post_payroll_je(run)


# ---------------------------------------------------------------------------
# Regression anchor: semi-monthly x timing mode x cutoff, REAL post path.
#
# BUG (fixed by this commit): compute_line always returned the FULL month's
# statutory (SSS/PhilHealth/Pag-IBIG) dict regardless of semi-monthly timing
# -- only the amount folded into net_pay was gated. PayrollRunLine.
# calculate_amounts() stores that (un-gated) dict verbatim onto sss_ee/
# philhealth_ee/pagibig_ee/etc, and PayrollRun.calculate_totals() sums those
# STORED per-line fields into the header buckets post_payroll_je's non-plug
# legs are built from. Two symptoms:
#   1. second_cutoff/first_cutoff: the cutoff where statutory does NOT apply
#      stored the full amount anyway, so the JE's non-plug legs (built from
#      the still-full buckets) disagreed with net_pay (which correctly
#      excluded the EE deduction) -- the plug guard raised ValueError. That
#      cutoff could not be posted AT ALL.
#   2. split_50_50: BOTH cutoffs stored the full amount (not halved), so
#      across the two cutoffs the EE deduction, ER expense, and payables were
#      each booked TWICE -- silently, since each cutoff's own plug still tied.
#
# These tests exercise the REAL post_payroll_je path (not just compute_line
# in isolation) for every timing mode x both cutoffs, proving (a) every
# cutoff now posts without raising and (b) the summed JE amounts across both
# cutoffs equal the correct full-month total -- not double-booked.
# ---------------------------------------------------------------------------

def _leg(je, code):
    """First JE line posted to the given account code, or None if that
    bucket was zero and _add_line skipped it entirely."""
    return next((l for l in je.lines if l.account.code == code), None)


def test_semi_monthly_second_cutoff_both_cutoffs_post_and_tie(app_ctx, posted_semi_run_factory):
    """Default 'second_cutoff' timing: cutoff 1 (statutory does NOT apply)
    used to raise ValueError on post -- the exact symptom #1 above. Both
    cutoffs must now post cleanly, each plug tying to its own net_pay, and
    cutoff 1 must carry ZERO statutory legs (nothing to post that cutoff)."""
    run1 = posted_semi_run_factory('PR-2026-06-S1', semi_period=1, semi_timing='second_cutoff')
    run2 = posted_semi_run_factory('PR-2026-06-S2', semi_period=2, semi_timing='second_cutoff')

    je1 = service.post_payroll_je(run1)   # must NOT raise
    je2 = service.post_payroll_je(run2)   # must NOT raise
    assert je1.is_balanced and je2.is_balanced

    # Cutoff 1: statutory does not apply -- only salaries expense + WHT payable.
    assert run1.total_net_pay == Decimal('18395.90')
    assert _leg(je1, '20501').credit_amount == Decimal('18395.90')   # plug == net_pay
    assert _leg(je1, '50210').debit_amount == Decimal('20000.00')
    assert _leg(je1, '20302').credit_amount == Decimal('1604.10')
    assert _leg(je1, '20402') is None   # SSS payable: nothing posted
    assert _leg(je1, '20403') is None   # PhilHealth payable: nothing posted
    assert _leg(je1, '20404') is None   # Pag-IBIG payable: nothing posted
    assert _leg(je1, '50212') is None   # SSS ER expense: nothing posted

    # Cutoff 2: statutory applies in full -- unaffected by this fix.
    assert run2.total_net_pay == Decimal('16035.90')
    assert _leg(je2, '20501').credit_amount == Decimal('16035.90')
    assert _leg(je2, '20402').credit_amount == Decimal('5280.00')   # SSS ee+er+ec
    assert _leg(je2, '20403').credit_amount == Decimal('2000.00')   # PhilHealth ee+er
    assert _leg(je2, '20404').credit_amount == Decimal('400.00')    # Pag-IBIG ee+er


def test_semi_monthly_first_cutoff_both_cutoffs_post_and_tie(app_ctx, posted_semi_run_factory):
    """'first_cutoff' timing: the mirror image -- cutoff 2 (statutory does
    NOT apply) is the one that used to raise ValueError on post."""
    run1 = posted_semi_run_factory('PR-2026-06-F1', semi_period=1, semi_timing='first_cutoff')
    run2 = posted_semi_run_factory('PR-2026-06-F2', semi_period=2, semi_timing='first_cutoff')

    je1 = service.post_payroll_je(run1)   # statutory applies -- was already OK
    je2 = service.post_payroll_je(run2)   # statutory does NOT apply -- must NOT raise

    assert run1.total_net_pay == Decimal('16035.90')
    assert _leg(je1, '20501').credit_amount == Decimal('16035.90')
    assert _leg(je1, '20402').credit_amount == Decimal('5280.00')

    assert run2.total_net_pay == Decimal('18395.90')
    assert _leg(je2, '20501').credit_amount == Decimal('18395.90')
    assert _leg(je2, '20402') is None
    assert _leg(je2, '20403') is None
    assert _leg(je2, '20404') is None


def test_semi_monthly_split_50_50_both_cutoffs_post_and_not_double_booked(app_ctx, posted_semi_run_factory):
    """'split_50_50' timing: both cutoffs post individually-consistent JEs
    (that part never raised -- each cutoff's own plug always tied), but the
    old bug booked the FULL month's EE deduction/ER expense/payables on BOTH
    cutoffs. This test proves the fix: summing the two cutoffs' JE legs
    yields the CORRECT full-month total (not double)."""
    run1 = posted_semi_run_factory('PR-2026-06-H1', semi_period=1, semi_timing='split_50_50')
    run2 = posted_semi_run_factory('PR-2026-06-H2', semi_period=2, semi_timing='split_50_50')

    je1 = service.post_payroll_je(run1)
    je2 = service.post_payroll_je(run2)
    assert je1.is_balanced and je2.is_balanced

    # Each cutoff individually gets HALF the full-month statutory.
    for run, je in ((run1, je1), (run2, je2)):
        assert run.total_net_pay == Decimal('17215.90')
        assert _leg(je, '20501').credit_amount == Decimal('17215.90')
        assert _leg(je, '20402').credit_amount == Decimal('2640.00')   # half of 5280
        assert _leg(je, '20403').credit_amount == Decimal('1000.00')   # half of 2000
        assert _leg(je, '20404').credit_amount == Decimal('200.00')    # half of 400

    # Summed across both cutoffs: the correct full-month total, not doubled.
    full_month_sss = Decimal('5280.00')       # sss_ee 1750 + sss_er 3500 + sss_ec 30
    full_month_philhealth = Decimal('2000.00')   # philhealth_ee 1000 + philhealth_er 1000
    full_month_pagibig = Decimal('400.00')       # pagibig_ee 200 + pagibig_er 200

    summed_sss = _leg(je1, '20402').credit_amount + _leg(je2, '20402').credit_amount
    summed_philhealth = _leg(je1, '20403').credit_amount + _leg(je2, '20403').credit_amount
    summed_pagibig = _leg(je1, '20404').credit_amount + _leg(je2, '20404').credit_amount

    assert summed_sss == full_month_sss
    assert summed_philhealth == full_month_philhealth
    assert summed_pagibig == full_month_pagibig
