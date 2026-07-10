"""Tie the imported books back to the legacy books.

`--commit` is refused unless this passes. Entries land POSTED and CAS has no
journal-entry edit route, so a wrong import has no in-app repair path -- the gate
is the safety net.

Three granularities, each catching a different failure:

  * grand total          -- a whole book silently not imported
  * per CAS account      -- a bad account map (amounts on the wrong code)
  * per account + month  -- corrupted dates (right totals, wrong periods)

`Dr == Cr` is deliberately NOT the test. A journal entry always balances by
construction, so balance proves nothing about whether the right amount reached
the right account in the right period.
"""
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal('0.00')


@dataclass(frozen=True)
class Discrepancy:
    key: tuple            # (cas_account_id, year, month)
    expected: tuple       # (debit, credit) per the legacy books
    actual: tuple         # (debit, credit) per CAS
    reason: str


def expected_totals(documents, account_map):
    """`{(cas_account_id, year, month): (debit, credit)}` from the legacy books."""
    totals = {}
    for doc in documents:
        year, month = doc.entry_date.year, doc.entry_date.month
        for line in doc.lines:
            key = (account_map[line.account_id], year, month)
            debit, credit = totals.get(key, (ZERO, ZERO))
            totals[key] = (debit + line.debit, credit + line.credit)
    return totals


def actual_totals(session, slug):
    """The same shape, read back out of CAS for this client's imported entries."""
    from sqlalchemy import extract, func

    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from scripts.legacy_import.persist import IMPORT_ENTRY_TYPE

    rows = (
        session.query(
            JournalEntryLine.account_id,
            extract('year', JournalEntry.entry_date),
            extract('month', JournalEntry.entry_date),
            func.sum(JournalEntryLine.debit_amount),
            func.sum(JournalEntryLine.credit_amount),
        )
        .join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
        .filter(
            JournalEntry.entry_type == IMPORT_ENTRY_TYPE,
            JournalEntry.source_ref.like(f'{slug}:%'),
        )
        .group_by(
            JournalEntryLine.account_id,
            extract('year', JournalEntry.entry_date),
            extract('month', JournalEntry.entry_date),
        )
    )
    return {
        (account_id, int(year), int(month)): (
            Decimal(str(debit or 0)).quantize(Decimal('0.01')),
            Decimal(str(credit or 0)).quantize(Decimal('0.01')),
        )
        for account_id, year, month, debit, credit in rows
    }


def compare_totals(expected, actual):
    """Every bucket that differs, in a stable order."""
    issues = []
    for key in sorted(set(expected) | set(actual)):
        want = expected.get(key)
        got = actual.get(key)

        if want is None:
            issues.append(Discrepancy(key, (ZERO, ZERO), got,
                                      'unexpected in CAS -- absent from the legacy books'))
        elif got is None:
            issues.append(Discrepancy(key, want, (ZERO, ZERO),
                                      'missing from CAS'))
        elif want != got:
            issues.append(Discrepancy(key, want, got, 'amount differs'))

    return issues


def grand_totals(totals):
    debit = sum((d for d, _c in totals.values()), ZERO)
    credit = sum((c for _d, c in totals.values()), ZERO)
    return debit, credit


def tieout_passed(issues):
    return not issues


def format_issues(issues, limit=25):
    """ASCII-only, bounded -- an import report must not dump 65k lines."""
    lines = []
    for issue in issues[:limit]:
        account_id, year, month = issue.key
        lines.append(
            f'  account {account_id} {year}-{month:02d}: '
            f'expected dr={issue.expected[0]} cr={issue.expected[1]} '
            f'got dr={issue.actual[0]} cr={issue.actual[1]} -- {issue.reason}'
        )
    if len(issues) > limit:
        lines.append(f'  ... and {len(issues) - limit} more')
    return '\n'.join(lines)
