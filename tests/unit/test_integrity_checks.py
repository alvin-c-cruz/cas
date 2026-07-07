"""Unit tests for the headless data-integrity checks (app/integrity/checks.py).

These back the /deploy skill's pre-flight gate: after a dry-run migration on a copy of a
client's real data, prove the books still balance and no data was silently lost.
"""
from decimal import Decimal
from datetime import date
import itertools

import pytest

from app.integrity.checks import run_checks, compute_aggregates, compare_aggregates

pytestmark = pytest.mark.unit

_counter = itertools.count(1)


def _je(db_session, main_branch, dr, cr, status='posted'):
    """A journal entry whose two lines total `dr` debit / `cr` credit. Codes/number are
    unique per call so a test can create several."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.accounts.models import Account
    n = next(_counter)
    a = Account(code=f'A{n:04d}', name=f'Cash{n}', account_type='Asset', normal_balance='debit', is_active=True)
    b = Account(code=f'B{n:04d}', name=f'Sales{n}', account_type='Revenue', normal_balance='credit', is_active=True)
    db_session.add_all([a, b]); db_session.commit()
    je = JournalEntry(entry_number=f'JE-{n}', entry_date=date(2026, 7, 8), description='t',
                      entry_type='journal', branch_id=main_branch.id, status=status,
                      total_debit=Decimal(dr), total_credit=Decimal(cr), is_balanced=(dr == cr))
    db_session.add(je); db_session.commit()
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=a.id,
                                    debit_amount=Decimal(dr), credit_amount=Decimal('0')))
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=b.id,
                                    debit_amount=Decimal('0'), credit_amount=Decimal(cr)))
    db_session.commit()
    return je


def _find(findings, name):
    return next(f for f in findings if f['check'] == name)


def test_balanced_books_all_ok(db_session, main_branch):
    _je(db_session, main_branch, '100', '100')
    findings = run_checks(db_session)
    assert _find(findings, 'posted_je_balanced')['ok'] is True
    assert _find(findings, 'trial_balance_zero')['ok'] is True
    assert _find(findings, 'je_line_orphans')['ok'] is True


def test_unbalanced_posted_je_flagged(db_session, main_branch):
    _je(db_session, main_branch, '100', '90')   # lines: 100 dr / 90 cr
    findings = run_checks(db_session)
    assert _find(findings, 'posted_je_balanced')['ok'] is False
    assert _find(findings, 'trial_balance_zero')['ok'] is False


def test_orphan_je_line_flagged(db_session, main_branch):
    from app.journal_entries.models import JournalEntryLine
    je = _je(db_session, main_branch, '100', '100')
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=3, account_id=999999,
                                    debit_amount=Decimal('0'), credit_amount=Decimal('0')))
    db_session.commit()
    assert _find(run_checks(db_session), 'je_line_orphans')['ok'] is False


def test_aggregates_capture_counts_and_tb(db_session, main_branch):
    _je(db_session, main_branch, '100', '100')
    agg = compute_aggregates(db_session)
    assert agg['tb_debit'] == '100.00' and agg['tb_credit'] == '100.00'
    assert agg['table_counts']['journal_entries'] == 1
    assert agg['table_counts']['journal_entry_lines'] == 2


def test_compare_aggregates_flags_delta(db_session, main_branch):
    _je(db_session, main_branch, '100', '100')
    before = compute_aggregates(db_session)
    _je(db_session, main_branch, '50', '50')          # a migration that changed data
    after = compute_aggregates(db_session)
    findings = compare_aggregates(before, after)
    assert any(f['ok'] is False for f in findings)


def test_compare_aggregates_identical_ok(db_session, main_branch):
    _je(db_session, main_branch, '100', '100')
    a = compute_aggregates(db_session)
    findings = compare_aggregates(a, dict(a))
    assert all(f['ok'] for f in findings)
