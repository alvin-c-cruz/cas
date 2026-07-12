"""Regression test for BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS (Journal Voucher).

Two users' browsers can both fetch the SAME suggested `entry_number` (neither has
committed yet). Deterministic repro: pre-commit a JournalEntry under the number a
fresh `generate_jv_number()` call would return (simulating "the other user already
won the race"), then POST a create carrying that same stale number (simulating "the
loser's browser still shows the old suggestion"). The create must still succeed with
a fresh, distinct number -- not silently discard the submission.

See docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md and the browser-level
repro clients/cas/ui-tests/concurrency_jv_concurrent_create.py.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry
from app.journal_entries.utils import generate_jv_number

pytestmark = [pytest.mark.integration, pytest.mark.journal_entries]


def _seed_accounts():
    debit_acct = Account(code='10500', name='Race Test Debit', account_type='Asset',
                          normal_balance='Debit', is_active=True)
    credit_acct = Account(code='40500', name='Race Test Credit', account_type='Revenue',
                           normal_balance='Credit', is_active=True)
    db.session.add_all([debit_acct, credit_acct])
    db.session.commit()
    return debit_acct, credit_acct


def _lines_json(debit_id, credit_id, amount='100.00'):
    return json.dumps([
        {'account_id': debit_id, 'description': 'race debit', 'debit': amount, 'credit': 0},
        {'account_id': credit_id, 'description': 'race credit', 'debit': 0, 'credit': amount},
    ])


def test_create_survives_a_number_already_taken_by_a_concurrent_commit(
        client, admin_user, main_branch, login_user):
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    debit_acct, credit_acct = _seed_accounts()

    taken_number = generate_jv_number(main_branch.id)
    winner = JournalEntry(
        entry_number=taken_number, entry_date=date.today(),
        description='concurrent winner', entry_type='adjustment',
        branch_id=main_branch.id, created_by_id=admin_user.id,
        status='draft', is_balanced=True,
        total_debit=Decimal('1.00'), total_credit=Decimal('1.00'),
    )
    db.session.add(winner)
    db.session.commit()

    resp = client.post('/journal-entries/create', data={
        'entry_number': taken_number,
        'entry_date': date.today().isoformat(),
        'description': 'concurrency test loser',
        'reference': '',
        'entry_type': 'adjustment',
        'lines': _lines_json(debit_acct.id, credit_acct.id),
    }, follow_redirects=False)

    loser = JournalEntry.query.filter_by(description='concurrency test loser').first()
    assert loser is not None, (
        "the second create must still succeed with a renumbered entry, not silently "
        f"vanish (response status was {resp.status_code})"
    )
    assert loser.entry_number != taken_number
    assert loser.entry_number.startswith('JV-')
