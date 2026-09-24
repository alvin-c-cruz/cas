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
    _je(db_session, main_branch, '50', '50')          # POSTED: the TB moves
    after = compute_aggregates(db_session)
    findings = compare_aggregates(before, after)
    assert _find(findings, 'aggregate_tb_debit')['ok'] is False


def test_compare_aggregates_identical_ok(db_session, main_branch):
    _je(db_session, main_branch, '100', '100')
    a = compute_aggregates(db_session)
    findings = compare_aggregates(a, dict(a))
    assert all(f['ok'] for f in findings)


# --- new-table drift: a CREATE TABLE is not data drift -----------------------
#
# `--compare-aggregates` is the schema-only deploy tier's assertion that a
# migration left DATA unchanged. It compared the union of table names, so a
# table that was ABSENT before and is PRESENT-AND-EMPTY after read as drift --
# which is precisely what an additive migration does. That blocked a real
# philgen deploy of pramd_0001 on 2026-08-20 with
# `drift: pr_amendment_requests:None->0`, every other check green.
#
# A gate that refuses routine, provably-safe migrations is worse than one that
# is merely strict: it trains whoever runs it to override, and then it protects
# nothing. Only the None->0 case is exempted; every other shape stays drift.

def _aggs(counts, dr='0', cr='0'):
    return {'table_counts': dict(counts), 'tb_debit': dr, 'tb_credit': cr}


def _row_counts_finding(findings):
    return next(f for f in findings if f['check'] == 'aggregate_row_counts')


def test_a_new_empty_table_is_not_drift():
    """The additive-migration case. THE fix."""
    before = _aggs({'users': 2})
    after = _aggs({'users': 2, 'pr_amendment_requests': 0})
    assert _row_counts_finding(compare_aggregates(before, after))['ok'] is True


def test_a_new_table_WITH_rows_is_still_drift():
    """CONTROL: a migration that CREATED DATA must still be caught. This is the
    assertion the exemption must not swallow."""
    before = _aggs({'users': 2})
    after = _aggs({'users': 2, 'backfilled_thing': 7})
    f = _row_counts_finding(compare_aggregates(before, after))
    assert f['ok'] is False
    assert 'backfilled_thing' in f['detail']


def test_a_dropped_table_is_still_drift():
    """CONTROL: a table vanishing is never routine, even when it was empty --
    the exemption is deliberately one-directional."""
    for count in (0, 5):
        before = _aggs({'users': 2, 'gone': count})
        after = _aggs({'users': 2})
        f = _row_counts_finding(compare_aggregates(before, after))
        assert f['ok'] is False, 'dropping a %d-row table was not flagged' % count


def test_an_existing_table_shrinking_is_still_drift():
    """CONTROL, narrowed 2026-09-24: SHRINKING is still drift. Users cannot
    hard-delete posted documents, so fewer rows means a migration removed data.
    Growth is a note now -- see the block below."""
    before = _aggs({'users': 3})
    after = _aggs({'users': 2})
    assert _row_counts_finding(compare_aggregates(before, after))['ok'] is False


def test_a_new_empty_table_alongside_real_drift_still_fails():
    """CONTROL: the exemption is per-table, not a blanket pass for the finding."""
    before = _aggs({'users': 3})
    after = _aggs({'users': 2, 'pr_amendment_requests': 0})
    f = _row_counts_finding(compare_aggregates(before, after))
    assert f['ok'] is False
    assert 'users' in f['detail']
    assert 'pr_amendment_requests' not in f['detail'], \
        'the exempt table should not be listed as drift'


# --- live-site drift: growth is a NOTE, not a failure --------------------------
#
# Three deploys in a row (2026-08-20, 09-22, 09-24) had `--compare-aggregates`
# report INTEGRITY FAILED on a green migration because a user was entering a
# document between the snapshot and the compare. The check assumed a quiescent
# database; production is not one. Twice the drift was in a FINANCIAL table and
# the runbook called that a rollback, and twice the operator overrode it after
# working out by hand that the new rows were DRAFTS -- outside the trial
# balance, which is why the TB totals had not moved.
#
# So the tiers are now: the TB totals, a table appearing WITH rows, a table
# vanishing, and a count SHRINKING stay hard (a migration that creates or
# deletes data). A count GROWING is reported as a note that names the new rows
# (identifier, status, created_at, user) so the operator reads the attribution
# instead of doing it in sqlite3 -- and if any of them were posted, the TB
# check has already failed on its own.

def test_growth_in_an_existing_table_is_a_note_not_drift():
    before = _aggs({'journal_entries': 43})
    after = _aggs({'journal_entries': 44})
    findings = compare_aggregates(before, after)
    assert _row_counts_finding(findings)['ok'] is True
    growth = _find(findings, 'aggregate_row_growth')
    assert growth['ok'] is True and growth['level'] == 'note'
    assert 'journal_entries:43->44' in growth['detail']


def test_a_finding_carries_a_level():
    """The CLI prints and exits on `level`; every finding must have one."""
    findings = compare_aggregates(_aggs({'users': 2}), _aggs({'users': 2}))
    assert all(f['level'] in ('ok', 'bad', 'note') for f in findings)
    assert _row_counts_finding(findings)['level'] == 'ok'
    assert _row_counts_finding(compare_aggregates(_aggs({'users': 2}),
                                                  _aggs({'users': 1})))['level'] == 'bad'


def test_growth_is_attributed_to_the_new_rows(db_session, main_branch):
    """The investigation the operator did by hand on 2026-09-24, automated: the
    note names the rows added since the snapshot, with their status."""
    _je(db_session, main_branch, '100', '100')
    before = compute_aggregates(db_session)
    je = _je(db_session, main_branch, '50', '50', status='draft')   # a user, mid-deploy
    after = compute_aggregates(db_session)
    findings = compare_aggregates(before, after, session=db_session)
    assert _find(findings, 'aggregate_tb_debit')['ok'] is True       # draft: TB untouched
    assert _row_counts_finding(findings)['ok'] is True
    detail = _find(findings, 'aggregate_row_growth')['detail']
    assert je.entry_number in detail and 'draft' in detail
    assert 'journal_entry_lines:2->4' in detail


def test_posted_growth_still_fails_on_the_tb_tier(db_session, main_branch):
    """CONTROL: a posted document between snapshots moves the TB, and that
    tier is untouched -- growth being a note does not weaken it."""
    _je(db_session, main_branch, '100', '100')
    before = compute_aggregates(db_session)
    _je(db_session, main_branch, '50', '50', status='posted')
    after = compute_aggregates(db_session)
    findings = compare_aggregates(before, after, session=db_session)
    assert _find(findings, 'aggregate_tb_debit')['ok'] is False


def test_a_snapshot_without_max_ids_still_compares(db_session, main_branch):
    """A baseline dumped by the previous version has no `table_max_ids`. It must
    still compare -- unattributed growth, not a crash mid-deploy."""
    _je(db_session, main_branch, '100', '100')
    before = compute_aggregates(db_session)
    before.pop('table_max_ids')
    _je(db_session, main_branch, '50', '50', status='draft')
    findings = compare_aggregates(before, compute_aggregates(db_session), session=db_session)
    growth = _find(findings, 'aggregate_row_growth')
    assert growth['ok'] is True and 'journal_entries:1->2' in growth['detail']
