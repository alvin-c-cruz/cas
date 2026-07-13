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
