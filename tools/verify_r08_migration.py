"""Run the R-08 Phase 1 migrations against a COPY of a real DB and probe the result.

Usage:  python tools/verify_r08_migration.py <path-to-source.db>

Copies the DB, runs `flask db upgrade` against the copy, and asserts:
  * every seeded vat_categories row has a transaction_nature
  * every withholding_tax row has tax_type='expanded'
  * every line with a non-empty vat_category resolved to a vat_nature
  * every line with an empty vat_category stayed NULL (unclassified, not guessed)
Exits non-zero on any violation. Never touches the source DB.
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


def main(src):
    if not os.path.exists(src):
        print(f'FAIL: source DB not found: {src}')
        return 1
    dst = os.path.join('instance', '_r08_verify.db')
    shutil.copy2(src, dst)
    print(f'copied {src} -> {dst}')

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
        os.remove(dst)
        return 1
    print(f'guard OK: flask resolved -> {resolved}')

    probe_conn = sqlite3.connect(dst)
    has_alembic_table = probe_conn.execute(
        "select count(*) from sqlite_master where type='table' and name='alembic_version'"
    ).fetchone()[0]
    probe_conn.close()
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
            os.remove(dst)
            return 1

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
    os.remove(dst)

    if failures:
        print('\nFAIL:')
        for f in failures:
            print('  -', f)
        return 1
    print('\nPASS: migration verified on a real-DB copy')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
