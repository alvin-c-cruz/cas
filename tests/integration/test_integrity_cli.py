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
