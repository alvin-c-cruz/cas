"""Write replayed legacy documents into CAS as posted journal vouchers.

Entries land POSTED because that is what the owner chose, and CAS has no
journal-entry edit route -- so this module's job is to make the write safe:

  * idempotent -- every entry carries `source_ref = '<slug>:<table>:<id>'` under a
    unique index, and a re-run skips what it already wrote
  * atomic -- one transaction; the caller commits, so an abort leaves nothing
  * reversible before go-live -- `purge_imported` deletes exactly the rows this
    module wrote (`entry_type='legacy_import'` AND `source_ref` for that client),
    never a voucher a human entered

Numbers are NOT minted by `generate_jv_number` -- they come from the legacy books
via `numbering.allocate_entry_numbers`, so RIC's documents keep the numbers RIC
already knows them by, and RIC continues each sequence after cutover.

Audit: the CLI has no `current_user`, so rather than writing 19k audit rows the
caller records one summary row (see BUG-IMPORT-AUDIT-NULLUSER). `created_by_id`
and `posted_by_id` are set to the admin user explicitly.
"""
from dataclasses import dataclass

from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.utils import ph_now

IMPORT_ENTRY_TYPE = 'legacy_import'   # 13 chars; the column is String(20)

# Flush in chunks so 19k entries + 65k lines do not sit in one giant unit of work.
_CHUNK = 1000


@dataclass
class WriteStats:
    written: int = 0
    skipped_existing: int = 0
    lines: int = 0


class BranchNotFoundError(RuntimeError):
    """The client's branch codes are not present in the target database."""


def source_ref_for(slug, doc):
    return f'{slug}:{doc.source_key}'


def existing_source_refs(session, slug):
    """Every `source_ref` this client has already imported."""
    prefix = f'{slug}:'
    rows = session.query(JournalEntry.source_ref).filter(
        JournalEntry.entry_type == IMPORT_ENTRY_TYPE,
        JournalEntry.source_ref.like(f'{prefix}%'),
    )
    return {row[0] for row in rows if row[0]}


def resolve_branch_ids(session, branch_codes):
    """`{'CORP': id, 'EXTRA': id}` from the client's real branch codes."""
    from app.branches.models import Branch

    resolved = {}
    for slot, code in branch_codes.items():
        branch = session.query(Branch).filter_by(code=code).first()
        if branch is None:
            raise BranchNotFoundError(
                f'branch code {code!r} (slot {slot}) not found in the target database'
            )
        resolved[slot] = branch.id
    return resolved


def admin_user_id(session):
    from app.users.models import User

    admin = session.query(User).filter_by(role='admin').first()
    if admin is None:
        raise RuntimeError('no admin user in the target database')
    return admin.id


def write_documents(session, slug, documents, allocated, account_map,
                    branch_ids, admin_user_id):
    """Insert each document as one posted `JournalEntry` plus its lines.

    Does NOT commit -- the caller owns the transaction, so a tie-out failure can
    roll the whole import back.
    """
    already = existing_source_refs(session, slug)
    now = ph_now()
    stats = WriteStats()

    pending = []
    for doc in documents:
        source_ref = source_ref_for(slug, doc)
        if source_ref in already:
            stats.skipped_existing += 1
            continue

        entry = JournalEntry(
            entry_number=allocated[(doc.book.prefix, doc.legacy_id)],
            entry_date=doc.entry_date,
            description=doc.description,
            reference=doc.number,
            entry_type=IMPORT_ENTRY_TYPE,
            is_reversing=False,
            total_debit=doc.total_debit,
            total_credit=doc.total_credit,
            is_balanced=True,
            status='posted',
            branch_id=branch_ids[doc.book.branch_code],
            created_by_id=admin_user_id,
            posted_by_id=admin_user_id,
            posted_at=now,
            source_ref=source_ref,
        )
        # Resolve every account BEFORE the entry is queued, so an unmapped account
        # aborts the transaction rather than writing a half-formed document.
        legs = [
            (number, account_map[line.account_id], line)
            for number, line in enumerate(doc.lines, start=1)
        ]
        pending.append((entry, legs))

        if len(pending) >= _CHUNK:
            stats.lines += _flush(session, pending)
            stats.written += len(pending)
            pending = []

    if pending:
        stats.lines += _flush(session, pending)
        stats.written += len(pending)

    return stats


def _flush(session, pending):
    """Add the chunk's headers, flush to assign ids, then bulk-insert the lines."""
    session.add_all(entry for entry, _legs in pending)
    session.flush()

    rows = []
    for entry, legs in pending:
        for line_number, account_id, line in legs:
            rows.append({
                'entry_id': entry.id,
                'line_number': line_number,
                'account_id': account_id,
                'description': line.description,
                'debit_amount': line.debit,
                'credit_amount': line.credit,
            })

    session.bulk_insert_mappings(JournalEntryLine, rows)
    return len(rows)


def purge_imported(session, slug):
    """Delete exactly the entries this importer wrote for `slug`. Does not commit.

    Scoped by BOTH `entry_type` and the client's `source_ref` prefix, so a voucher
    a human entered in CAS can never be caught by it.
    """
    entries = session.query(JournalEntry.id).filter(
        JournalEntry.entry_type == IMPORT_ENTRY_TYPE,
        JournalEntry.source_ref.like(f'{slug}:%'),
    )
    ids = [row[0] for row in entries]
    if not ids:
        return 0

    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        session.query(JournalEntryLine).filter(
            JournalEntryLine.entry_id.in_(chunk)
        ).delete(synchronize_session=False)
        session.query(JournalEntry).filter(
            JournalEntry.id.in_(chunk)
        ).delete(synchronize_session=False)

    # A bulk delete does not evict cached lazy relationships.
    session.expire_all()
    return len(ids)
