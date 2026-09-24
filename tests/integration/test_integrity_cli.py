"""Integration smoke for the `flask integrity-check` CLI (app/integrity/cli.py)."""
import json
from decimal import Decimal
from datetime import date
import pytest

pytestmark = pytest.mark.integration


def _post_balanced(db_session, main_branch):
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.accounts.models import Account
    a = Account(code='1000', name='Cash', account_type='Asset', normal_balance='debit', is_active=True)
    b = Account(code='4000', name='Sales', account_type='Revenue', normal_balance='credit', is_active=True)
    db_session.add_all([a, b]); db_session.commit()
    je = JournalEntry(entry_number='JE-CLI', entry_date=date(2026, 7, 8), description='t',
                      entry_type='journal', branch_id=main_branch.id, status='posted',
                      total_debit=Decimal('10'), total_credit=Decimal('10'), is_balanced=True)
    db_session.add(je); db_session.commit()
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=a.id, debit_amount=Decimal('10'), credit_amount=Decimal('0')))
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=b.id, debit_amount=Decimal('0'), credit_amount=Decimal('10')))
    db_session.commit()


def test_integrity_check_json_ok(app, db_session, main_branch):
    _post_balanced(db_session, main_branch)
    result = app.test_cli_runner().invoke(args=['integrity-check', '--json'])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload['ok'] is True
    assert all(f['ok'] for f in payload['findings'])


def test_dump_and_compare_aggregates(app, db_session, main_branch, tmp_path):
    _post_balanced(db_session, main_branch)
    runner = app.test_cli_runner()
    base = tmp_path / 'pre.json'
    assert runner.invoke(args=['integrity-check', '--dump-aggregates', str(base)]).exit_code == 0
    # unchanged -> compare passes
    assert runner.invoke(args=['integrity-check', '--compare-aggregates', str(base)]).exit_code == 0


def _user_je(db_session, main_branch, number, status='draft'):
    """What a user does during the deploy window: enters a document."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.accounts.models import Account
    a = Account.query.filter_by(code='1000').one()
    b = Account.query.filter_by(code='4000').one()
    je = JournalEntry(entry_number=number, entry_date=date(2026, 9, 24), description='opening',
                      entry_type='opening', branch_id=main_branch.id, status=status,
                      total_debit=Decimal('7'), total_credit=Decimal('7'), is_balanced=True)
    db_session.add(je); db_session.commit()
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=a.id, debit_amount=Decimal('7'), credit_amount=Decimal('0')))
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=b.id, debit_amount=Decimal('0'), credit_amount=Decimal('7')))
    db_session.commit()
    return je


def test_a_draft_entered_during_the_deploy_window_is_a_note_not_a_failure(
        app, db_session, main_branch, tmp_path):
    """The 2026-09-22 and 2026-09-24 deploys, as a test. Snapshot; a user saves a
    DRAFT while the migration runs; compare. Exit 0, and the output names the
    document so nobody has to open sqlite3 to find out what moved."""
    _post_balanced(db_session, main_branch)
    runner = app.test_cli_runner()
    base = tmp_path / 'pre.json'
    assert runner.invoke(args=['integrity-check', '--dump-aggregates', str(base)]).exit_code == 0
    _user_je(db_session, main_branch, 'JV-2026-09-0003')
    result = runner.invoke(args=['integrity-check', '--compare-aggregates', str(base)])
    assert result.exit_code == 0, result.output
    assert 'INTEGRITY OK' in result.output
    assert '[NOTE] aggregate_row_growth' in result.output
    assert 'JV-2026-09-0003' in result.output and 'draft' in result.output


def test_a_posted_entry_during_the_window_still_fails(app, db_session, main_branch, tmp_path):
    """CONTROL: the hard tier is untouched. Posted rows move the trial balance."""
    _post_balanced(db_session, main_branch)
    runner = app.test_cli_runner()
    base = tmp_path / 'pre.json'
    runner.invoke(args=['integrity-check', '--dump-aggregates', str(base)])
    _user_je(db_session, main_branch, 'JV-POSTED', status='posted')
    result = runner.invoke(args=['integrity-check', '--compare-aggregates', str(base)])
    assert result.exit_code == 1
    assert '[BAD] aggregate_tb_debit' in result.output
