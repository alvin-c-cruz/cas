"""Headless data-integrity checks over a SQLAlchemy session.

Pure functions -- no Flask request context, no Playwright. Used by the
`flask integrity-check` CLI and, through it, by the /deploy skill's pre-flight gate to
prove a client's real data survives a schema migration intact.
"""
from decimal import Decimal

from sqlalchemy import inspect as sa_inspect

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.accounts.models import Account


def _finding(check, ok, detail=''):
    return {'check': check, 'ok': bool(ok), 'detail': detail}


def _dec(v):
    return Decimal(str(v or 0))


def run_checks(session):
    """Return a list of findings; ok=False marks a violation."""
    findings = []

    # 1. Every POSTED journal entry balances (sum of its line debits == sum of credits).
    rows = session.query(
        JournalEntry.entry_number,
        db.func.coalesce(db.func.sum(JournalEntryLine.debit_amount), 0),
        db.func.coalesce(db.func.sum(JournalEntryLine.credit_amount), 0),
    ).join(JournalEntryLine, JournalEntryLine.entry_id == JournalEntry.id) \
     .filter(JournalEntry.status == 'posted') \
     .group_by(JournalEntry.id).all()
    unbalanced = [f'{num}({_dec(dr)}!={_dec(cr)})' for num, dr, cr in rows if _dec(dr) != _dec(cr)]
    findings.append(_finding('posted_je_balanced', not unbalanced,
                             ('unbalanced: ' + ', '.join(unbalanced)) if unbalanced else 'all balanced'))

    # 2. Global trial balance nets to zero across all POSTED lines.
    tb_dr = session.query(db.func.coalesce(db.func.sum(JournalEntryLine.debit_amount), 0)) \
        .join(JournalEntry).filter(JournalEntry.status == 'posted').scalar()
    tb_cr = session.query(db.func.coalesce(db.func.sum(JournalEntryLine.credit_amount), 0)) \
        .join(JournalEntry).filter(JournalEntry.status == 'posted').scalar()
    findings.append(_finding('trial_balance_zero', _dec(tb_dr) == _dec(tb_cr),
                             f'debit={_dec(tb_dr)} credit={_dec(tb_cr)}'))

    # 3. No JE line points at a missing entry or a missing account (orphan FKs).
    acct_ids = {a[0] for a in session.query(Account.id).all()}
    je_ids = {j[0] for j in session.query(JournalEntry.id).all()}
    orphans = []
    for l in session.query(JournalEntryLine).all():
        if l.entry_id not in je_ids:
            orphans.append(f'line{l.id}->entry{l.entry_id}')
        if l.account_id is not None and l.account_id not in acct_ids:
            orphans.append(f'line{l.id}->acct{l.account_id}')
    findings.append(_finding('je_line_orphans', not orphans,
                             ('orphans: ' + ', '.join(orphans)) if orphans else 'none'))

    # 4. Each posted source voucher references a non-null, existing JE.
    findings.append(_voucher_je_valid(session, je_ids))
    return findings


def _voucher_je_valid(session, je_ids):
    bad = []
    for mod, cls, label in (
        ('app.cash_disbursements.models', 'CashDisbursementVoucher', 'CDV'),
        ('app.cash_receipts.models', 'CashReceiptVoucher', 'CRV'),
    ):
        Model = getattr(__import__(mod, fromlist=[cls]), cls)
        for v in session.query(Model).filter(Model.status == 'posted').all():
            if not v.journal_entry_id or v.journal_entry_id not in je_ids:
                bad.append(f'{label}:{getattr(v, "id", "?")}')
    return _finding('voucher_je_valid', not bad,
                    ('posted vouchers with missing JE: ' + ', '.join(bad)) if bad else 'all valid')


def compute_aggregates(session):
    """Point-in-time aggregates that a SCHEMA-only migration must leave unchanged.

    Decimals are stored as `str` so the dict round-trips through JSON stably.
    """
    counts = {}
    for table in sa_inspect(session.get_bind()).get_table_names():
        counts[table] = session.execute(db.text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
    tb_dr = session.query(db.func.coalesce(db.func.sum(JournalEntryLine.debit_amount), 0)) \
        .join(JournalEntry).filter(JournalEntry.status == 'posted').scalar()
    tb_cr = session.query(db.func.coalesce(db.func.sum(JournalEntryLine.credit_amount), 0)) \
        .join(JournalEntry).filter(JournalEntry.status == 'posted').scalar()
    return {'table_counts': counts, 'tb_debit': str(_dec(tb_dr)), 'tb_credit': str(_dec(tb_cr))}


def compare_aggregates(before, after):
    """Findings for any drift between two aggregate snapshots (ok=False on drift)."""
    findings = []
    for key in ('tb_debit', 'tb_credit'):
        findings.append(_finding(f'aggregate_{key}', before.get(key) == after.get(key),
                                 f'{before.get(key)} -> {after.get(key)}'))
    tables = set(before.get('table_counts', {})) | set(after.get('table_counts', {}))
    drift = []
    for t in sorted(tables):
        b = before.get('table_counts', {}).get(t)
        a = after.get('table_counts', {}).get(t)
        if b != a:
            drift.append(f'{t}:{b}->{a}')
    findings.append(_finding('aggregate_row_counts', not drift,
                             ('drift: ' + ', '.join(drift)) if drift else 'unchanged'))
    return findings
