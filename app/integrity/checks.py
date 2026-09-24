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


def _finding(check, ok, detail='', note=False):
    """A finding. `level` is what the CLI prints and exits on:
        ok   -> passed
        bad  -> failed; the run exits 1
        note -> passed, but says something the operator should read
    `ok` stays the boolean every caller already reads; a note is ok."""
    if note:
        return {'check': check, 'ok': True, 'level': 'note', 'detail': detail}
    return {'check': check, 'ok': bool(ok), 'level': 'ok' if ok else 'bad', 'detail': detail}


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
    counts, max_ids = {}, {}
    insp = sa_inspect(session.get_bind())
    for table in insp.get_table_names():
        counts[table] = session.execute(db.text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
        # The high-water mark lets compare_aggregates() NAME the rows added since
        # the snapshot, instead of only counting them. Only for tables with an id.
        if any(c['name'] == 'id' for c in insp.get_columns(table)):
            max_ids[table] = session.execute(db.text(f'SELECT MAX(id) FROM "{table}"')).scalar()
    tb_dr = session.query(db.func.coalesce(db.func.sum(JournalEntryLine.debit_amount), 0)) \
        .join(JournalEntry).filter(JournalEntry.status == 'posted').scalar()
    tb_cr = session.query(db.func.coalesce(db.func.sum(JournalEntryLine.credit_amount), 0)) \
        .join(JournalEntry).filter(JournalEntry.status == 'posted').scalar()
    return {'table_counts': counts, 'table_max_ids': max_ids,
            'tb_debit': str(_dec(tb_dr)), 'tb_credit': str(_dec(tb_cr))}


# Attributes tried, in order, to name a new row in the growth note. Not a per-table
# list: whatever model maps the table supplies the first one it has.
_IDENT_ATTRS = ('entry_number', 'cdv_number', 'crv_number', 'ap_number', 'po_number',
                'pr_number', 'rr_number', 'so_number', 'si_number', 'dr_number',
                'reference', 'number', 'code', 'username', 'name')
_GROWTH_ROWS_SHOWN = 5


def _model_for(table):
    for mapper in db.Model.registry.mappers:
        if mapper.local_table is not None and mapper.local_table.name == table:
            return mapper.class_
    return None


def _describe_new_rows(session, table, since_id):
    """'JV-0003 (draft, 2026-09-24 07:46:45, user 1); ...' for the rows of `table`
    with id > since_id, or '' when the table has no mapped model to read them with."""
    Model = _model_for(table)
    if Model is None or not hasattr(Model, 'id'):
        return ''
    rows = session.query(Model).filter(Model.id > since_id).order_by(Model.id).limit(_GROWTH_ROWS_SHOWN + 1).all()
    ident = next((a for a in _IDENT_ATTRS if hasattr(Model, a)), None)
    out = []
    for r in rows[:_GROWTH_ROWS_SHOWN]:
        bits = [str(getattr(r, ident)) if ident else f'id {r.id}']
        for attr, fmt in (('status', '{}'), ('created_at', '{:%Y-%m-%d %H:%M:%S}'),
                          ('created_by_id', 'user {}'), ('user_id', 'user {}')):
            v = getattr(r, attr, None)
            if v is not None:
                bits.append(fmt.format(v))
        out.append(f'{bits[0]} ({", ".join(bits[1:])})' if len(bits) > 1 else bits[0])
    if len(rows) > _GROWTH_ROWS_SHOWN:
        out.append('...')
    return '; '.join(out)


def compare_aggregates(before, after, session=None):
    """Findings for drift between two aggregate snapshots.

    HARD (ok=False): the posted trial-balance totals; a table that appeared WITH
    rows; a table that vanished; a count that SHRANK. Those are what a migration
    that created or deleted data looks like.

    NOTE (ok=True, level 'note'): a count that GREW. On a live site that is what
    a user saving a document during the deploy window looks like, and three
    deploys in a row (2026-08-20, 09-22, 09-24) failed this gate on exactly that,
    twice in a financial table the runbook then called a rollback. Growth is
    reported with the new rows named (when `session` is given and the baseline
    carries `table_max_ids`) so the operator reads the attribution instead of
    doing it by hand. A posted document among them has already failed the TB
    tier above, so this does not weaken the gate on anything the books care about.
    """
    findings = []
    for key in ('tb_debit', 'tb_credit'):
        findings.append(_finding(f'aggregate_{key}', before.get(key) == after.get(key),
                                 f'{before.get(key)} -> {after.get(key)}'))
    tables = set(before.get('table_counts', {})) | set(after.get('table_counts', {}))
    drift, growth = [], []
    for t in sorted(tables):
        b = before.get('table_counts', {}).get(t)
        a = after.get('table_counts', {}).get(t)
        if b == a:
            continue
        if b is not None and a is not None and a > b:
            since = before.get('table_max_ids', {}).get(t)
            who = _describe_new_rows(session, t, since) if session is not None and since is not None else ''
            growth.append(f'{t}:{b}->{a}' + (f' [{who}]' if who else ''))
            continue
        # A table that did not exist before and is EMPTY after is what an
        # additive migration does -- it is a schema change with no data in it,
        # which is exactly what this tier permits. Flagging it blocked a real
        # philgen deploy of pramd_0001 (`drift: pr_amendment_requests:None->0`)
        # with every other check green.
        #
        # ONE-DIRECTIONAL AND COUNT-SENSITIVE, deliberately:
        #   * None -> N>0 stays drift: the migration CREATED DATA, which this
        #     tier does not permit and which is the case worth catching.
        #   * N -> None (dropped) stays drift at any count, including 0: a table
        #     vanishing is never routine, and the aggregate snapshot is the last
        #     place it would otherwise be visible.
        # Skipping the entry rather than passing the whole finding keeps this
        # per-table, so a genuine drift in the same migration still fails.
        if b is None and a == 0:
            continue
        drift.append(f'{t}:{b}->{a}')
    findings.append(_finding('aggregate_row_counts', not drift,
                             ('drift: ' + ', '.join(drift)) if drift else 'unchanged'))
    if growth:
        findings.append(_finding('aggregate_row_growth', True, note=True,
                                 detail='rows added since the snapshot: ' + ', '.join(growth)))
    return findings
