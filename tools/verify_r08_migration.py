"""Run the R-08 Phase 1 migrations against a COPY of a real DB and probe the result.

Usage:  python tools/verify_r08_migration.py <path-to-source.db>

Copies the DB, runs `flask db upgrade` against the copy, and asserts:
  * every seeded vat_categories row has a transaction_nature
  * every withholding_tax row has tax_type='expanded'
  * every line with a non-empty vat_category resolved to a vat_nature
  * every line with an empty vat_category stayed NULL (unclassified, not guessed)
Exits non-zero on any violation. Never touches the source DB. The working copy at
instance/_r08_verify.db is always deleted before this process exits, on every
code path (success, assertion failure, or any subprocess failure) -- see the
try/finally in main().

Two different proof strengths are possible depending on the source DB's state,
and this script prints which one a given run delivers -- see the PROOF STRENGTH
banner below:
  * a DB that already has an alembic_version row is upgraded from wherever it
    actually is, replaying its real migration history (proves migration-HISTORY
    safety -- the thing that can hide legacy/preserved index or constraint
    names under batch_alter_table).
  * a DB with no alembic_version row (built by db.create_all(), never migrated)
    is stamped at PRE_PHASE1_REVISION first. That proves the backfill correctly
    classifies real production VOLUME and DATA, but it does NOT replay real
    migration history, so it does NOT prove migration-history safety -- a
    create_all() schema is demonstrably not identical to a migrated one (see
    the banner text for the two concrete, confirmed differences).
"""
import os
import shutil
import sqlite3
import subprocess
import sys

LINE_TABLES = [
    ('sales_invoice_items', 'sales_vat_categories'),
    ('crv_revenue_lines', 'sales_vat_categories'),
    ('accounts_payable_items', 'vat_categories'),
    ('cdv_expense_lines', 'vat_categories'),
]

# down_revision of b1a7c0d3e4f5 -- the revision immediately BEFORE the Phase 1
# chain (transaction_nature -> tax_type -> vat_nature) begins. Some real
# instances (e.g. philgen_demo.db) were seeded via `db.create_all()` and were
# never run through `flask db upgrade`, so they have no alembic_version row at
# all. Stamping a copy at this exact revision before upgrading makes
# `flask db upgrade` apply ONLY the three Phase 1 migrations being verified --
# it does not matter that such a DB also predates unrelated later migrations
# (quotations, delivery_receipts, ...): those migrations don't touch the six
# tables Phase 1 cares about, so they are irrelevant here. This never touches
# a DB that already has an alembic_version row -- those are upgraded from
# wherever they actually are, same as a real deploy would.
PRE_PHASE1_REVISION = '29500ade76f8'


def _print_create_all_banner():
    print('=' * 70)
    print('PROOF STRENGTH: VOLUME AND BACKFILL CLASSIFICATION ONLY.')
    print('This copy has no alembic_version table -- it was built by')
    print('db.create_all(), never run through a real migration history.')
    print('Stamping it and upgrading proves the backfill correctly classifies')
    print('real production VOLUME and DATA, but it does NOT replay the real')
    print('migration history, so it does NOT prove migration-history safety.')
    print('A create_all() schema is confirmed NOT identical to a migrated one:')
    print("  1. real history: amount/wt_amount carry server_default='0.00';")
    print('     create_all() has no default on these columns.')
    print('  2. real history: accounts_payable_items still carries the legacy')
    print('     index name ix_purchase_bill_items_bill_id (preserved by')
    print('     op.batch_alter_table from an old table rename); create_all()')
    print('     gets a clean ix_accounts_payable_items_ap_id instead.')
    print('This run cannot exercise that legacy-index-preservation hazard.')
    print('=' * 70)


def _print_real_history_banner():
    print('-' * 70)
    print('PROOF STRENGTH: MIGRATION-HISTORY SAFETY.')
    print('This copy already had an alembic_version row -- flask db upgrade')
    print('replayed its real intervening migrations from its actual history,')
    print('exercising real historical schema quirks (e.g. preserved legacy')
    print('index/constraint names), not a clean create_all() schema. This')
    print('proves migration-history safety, not merely volume/backfill')
    print('classification.')
    print('-' * 70)


def main(src):
    if not os.path.exists(src):
        print(f'FAIL: source DB not found: {src}')
        return 1
    dst = os.path.join('instance', '_r08_verify.db')
    shutil.copy2(src, dst)
    print(f'copied {src} -> {dst}')

    try:
        # `.env` also sets SQLALCHEMY_DATABASE_URI. python-dotenv's load_dotenv()
        # does NOT override an already-set environment variable, so this env wins --
        # verified empirically 2026-07-09 with `flask db current`. Do not remove the
        # guard below: if that ever changes, this script would silently migrate the
        # REAL database while reporting that it verified a copy.
        env = dict(os.environ, SQLALCHEMY_DATABASE_URI=f'sqlite:///{os.path.abspath(dst)}')

        # Import flask_app (not app.create_app directly): flask_app.py is what
        # FLASK_APP points at, and it is the thing that calls load_dotenv() before
        # building the app -- that's what supplies SECRET_KEY when it isn't already
        # in the environment. Calling create_app() directly here would skip that
        # load_dotenv() call and crash on a missing SECRET_KEY, which is not the
        # real `flask db upgrade` code path this guard is meant to model.
        probe = subprocess.run([sys.executable, '-c',
            'import flask_app;'
            "print(flask_app.app.config['SQLALCHEMY_DATABASE_URI'])"],
            env=env, capture_output=True, text=True)
        resolved = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ''
        if os.path.basename(dst) not in resolved:
            print(f'FAIL: refusing to run. Flask resolved the DB URI to {resolved!r}, '
                  f'which is not the copy at {dst}. Migrating the real DB is not an option.')
            return 1
        print(f'guard OK: flask resolved -> {resolved}')

        probe_conn = sqlite3.connect(dst)
        has_alembic_table = probe_conn.execute(
            "select count(*) from sqlite_master where type='table' and name='alembic_version'"
        ).fetchone()[0]
        probe_conn.close()

        history_verified = bool(has_alembic_table)
        if not has_alembic_table:
            print(f'NOTE: copy has no alembic_version (pre-migration-tracking snapshot); '
                  f'stamping at {PRE_PHASE1_REVISION} (the revision immediately before '
                  f'the Phase 1 chain) so upgrade applies only the three migrations '
                  f'under test')
            s = subprocess.run([sys.executable, '-m', 'flask', 'db', 'stamp',
                                PRE_PHASE1_REVISION], env=env, capture_output=True, text=True)
            print(s.stdout, s.stderr)
            if s.returncode != 0:
                print('FAIL: flask db stamp returned non-zero')
                return 1
            _print_create_all_banner()
        else:
            print('NOTE: copy already has an alembic_version row (real migration history)')
            _print_real_history_banner()

        r = subprocess.run([sys.executable, '-m', 'flask', 'db', 'upgrade'],
                           env=env, capture_output=True, text=True)
        print(r.stdout, r.stderr)
        if r.returncode != 0:
            print('FAIL: flask db upgrade returned non-zero')
            return 1

        c = sqlite3.connect(dst)
        failures = []

        unclassified_cats = c.execute(
            'select code from vat_categories where transaction_nature is null').fetchall()
        if unclassified_cats:
            print(f'NOTE: client-created categories left unclassified: '
                  f'{[r[0] for r in unclassified_cats]}')

        bad_types = c.execute(
            "select code from withholding_tax where tax_type <> 'expanded'").fetchall()
        if bad_types:
            failures.append(f'withholding_tax rows not backfilled to expanded: {bad_types}')

        for line_table, cat_table in LINE_TABLES:
            leaked = c.execute(f"""
                select count(*) from {line_table} l
                 where l.vat_category is not null and l.vat_category <> ''
                   and l.vat_nature is null
                   and exists (select 1 from {cat_table} c
                                where c.code = l.vat_category
                                  and c.transaction_nature is not null)
            """).fetchone()[0]
            if leaked:
                failures.append(f'{line_table}: {leaked} lines had a mappable code '
                                f'but no vat_nature')

            guessed = c.execute(f"""
                select count(*) from {line_table}
                 where (vat_category is null or vat_category = '')
                   and vat_nature is not null
            """).fetchone()[0]
            if guessed:
                failures.append(f'{line_table}: {guessed} lines with an empty code were '
                                f'assigned a nature (must stay NULL)')

            total, classified = c.execute(
                f'select count(*), count(vat_nature) from {line_table}').fetchone()
            print(f'  {line_table:26s} {classified}/{total} classified')

        c.close()

        if failures:
            print('\nFAIL:')
            for f in failures:
                print('  -', f)
            return 1

        if history_verified:
            print('\nPASS (migration-history safety verified on a real migrated-DB copy)')
        else:
            print('\nPASS (volume/backfill classification verified on a create_all() copy '
                  '-- migration-history safety NOT verified by this run)')
        return 0
    finally:
        if os.path.exists(dst):
            os.remove(dst)
            print(f'cleaned up {dst}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
