"""CLI entry point for the legacy GL replay.

    python -m scripts.legacy_import.run --client ric                # dry run
    python -m scripts.legacy_import.run --client ric --commit       # writes
    python -m scripts.legacy_import.run --client ric --purge        # undo (pre go-live)

Order of safety checks, all before a single row is written:
  1. the client must be enabled
  2. the app's database filename must be exactly this client's
  3. every used legacy account must resolve
  4. every entry number must be globally unique
  5. every document must balance
  6. the tie-out must pass -- otherwise the transaction is rolled back even
     under --commit

Entries land POSTED and CAS has no journal-entry edit route, so `--commit`
without a passing tie-out is refused rather than warned about.
"""
import argparse
import sqlite3
import sys

from scripts.legacy_import import account_map as amap
from scripts.legacy_import import masterdata, persist, report, tieout
from scripts.legacy_import.clients import (
    ClientDisabledError,
    UnknownClientError,
    WrongTargetError,
    assert_target_database,
    get_client,
)
from scripts.legacy_import.numbering import allocate_entry_numbers, duplicate_groups
from scripts.legacy_import.reader import read_documents
from scripts.legacy_import.schema import BOOKS


def open_legacy(client):
    if not client.legacy_db.exists():
        raise SystemExit(f'legacy database not found: {client.legacy_db}')
    return sqlite3.connect(f'file:{client.legacy_db}?mode=ro', uri=True)


def collect(conn):
    """Read every book. Returns (documents, per_book rows, skipped, number rows)."""
    documents, per_book, skipped, number_rows = [], [], {}, []

    for book in BOOKS:
        docs, book_skipped = read_documents(conn, book)
        documents.extend(docs)
        skipped[book.header_table] = book_skipped
        per_book.append({
            'book': book.header_table,
            'prefix': book.prefix,
            'branch': book.branch_code,
            'documents': len(docs),
            'lines': sum(len(d.lines) for d in docs),
            'skipped': len(book_skipped),
        })
        # Numbers are allocated over ALL headers, including skipped ones, so a
        # skipped header can never free up a number a kept one would collide with.
        rows = conn.execute(
            f'SELECT id, "{book.number_column}" FROM "{book.header_table}"'
        ).fetchall()
        number_rows.extend((book.prefix, legacy_id, raw) for legacy_id, raw in rows)

    return documents, per_book, skipped, number_rows


def main(argv=None):
    parser = argparse.ArgumentParser(description='Replay a legacy accounting DB into CAS')
    parser.add_argument('--client', required=True, help='client slug (e.g. ric)')
    parser.add_argument('--commit', action='store_true', help='write (default: dry run)')
    parser.add_argument('--purge', action='store_true',
                        help='delete this client\'s imported entries and exit')
    args = parser.parse_args(argv)

    # A guard firing is an expected outcome, not a crash -- report it plainly.
    try:
        client = get_client(args.client)      # (1) enabled?
    except (UnknownClientError, ClientDisabledError) as exc:
        raise SystemExit(f'REFUSED: {exc}')

    from app import db
    from flask_app import app

    with app.app_context():
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        try:
            assert_target_database(uri, client)   # (2) right database?
        except WrongTargetError as exc:
            raise SystemExit(f'REFUSED: {exc}')

        print(f'TARGET : {uri}')
        print(f'LEGACY : {client.legacy_db}')

        if args.purge:
            removed = persist.purge_imported(db.session, client.slug)
            if args.commit:
                db.session.commit()
                print(f'PURGED : {removed} imported entries removed.')
            else:
                db.session.rollback()
                print(f'DRY RUN: would remove {removed} imported entries. Add --commit.')
            print('NOTE   : imported customers and vendors are NOT purged -- they are '
                  'master data a user may have since edited. Remove them by hand if wanted.')
            return 0

        conn = open_legacy(client)
        admin_id = persist.admin_user_id(db.session)
        branch_ids = persist.resolve_branch_ids(db.session, client.branch_codes)

        account_map = amap.build_account_map(conn, db.session, client.recodes)   # (3)
        documents, per_book, skipped, number_rows = collect(conn)                # (5) balance
        allocated = allocate_entry_numbers(number_rows)                          # (4) unique
        duplicates = duplicate_groups(number_rows)

        master = masterdata.import_master_data(db.session, conn, admin_id)
        persist.write_documents(
            session=db.session, slug=client.slug, documents=documents,
            allocated=allocated, account_map=account_map,
            branch_ids=branch_ids, admin_user_id=admin_id,
        )
        db.session.flush()

        expected = tieout.expected_totals(documents, account_map)
        actual = tieout.actual_totals(db.session, client.slug)
        issues = tieout.compare_totals(expected, actual)                          # (6)
        grand = tieout.grand_totals(expected)

        committed = False
        if args.commit and not issues:
            db.session.commit()
            committed = True
        else:
            db.session.rollback()

        print(report.render(client, per_book, skipped, duplicates, master,
                            grand, issues, committed))
        note = report.petty_cash_note(per_book)
        if note:
            print(note)

        if issues:
            print('\nABORTED: tie-out failed; nothing was written.', file=sys.stderr)
            return 1
        if not args.commit:
            return 0

        print('\nOK: import committed and tied out.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
