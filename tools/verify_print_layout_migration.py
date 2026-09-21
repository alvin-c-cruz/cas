"""Verify the prnlay_0002 seeding migration reproduces IDENTICAL PO print output.

Usage:  python tools/verify_print_layout_migration.py <path-to-source.db>

Modelled on tools/verify_r08_migration.py: copies the DB, runs `flask db upgrade`
against the copy only, and asserts:

  1. get_layout(branch_id) -- the actual function the print page calls -- returns
     a byte-for-byte identical dict for EVERY branch in the DB, and for the
     unscoped case (branch_id=None), before vs. after prnlay_0002 runs. This is
     the proof that matters: if printing changes even one pixel, this fails
     loudly with a diff and a non-zero exit, and the feature does not ship.
  2. The migration actually created at least one named_print_layouts row
     (doc_type='purchase_orders') -- a silent no-op would pass check 1 for the
     wrong reason (nothing to migrate) if the source DB is empty of layouts.
  3. The separate, unrelated LEGACY `print_layouts` table (an abandoned 2026
     attempt at this same problem -- NOT what this feature writes to) is left
     completely alone: same CREATE TABLE schema, same row count, before and
     after. Deleting from or altering that table would destroy someone else's
     schema; this is the check that proves it didn't happen.

Never touches the source DB. The working copy at instance/_print_layout_verify.db
is always deleted before this process exits, on every code path (success,
assertion failure, or any subprocess failure) -- see the try/finally in main().

Every DB access that runs application code (get_layout, which imports
Flask-SQLAlchemy-bound models) happens in a throwaway subprocess bound to the
copy via SQLALCHEMY_DATABASE_URI -- this script's own process never binds
Flask-SQLAlchemy to the working copy, only ever launches children that do.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys


def _print_layouts_schema(conn):
    return conn.execute(
        "select sql from sqlite_master where type='table' and name='print_layouts'"
    ).fetchone()


def _record_layouts(env, scopes):
    """Call get_layout(branch_id) for every scope, in a fresh subprocess bound to
    the working copy DB. Returns {scope: layout_dict}."""
    script = (
        'import json, sys\n'
        'import flask_app\n'
        'from app.purchase_orders.preprinted_layout import get_layout\n'
        'scopes = json.loads(sys.argv[1])\n'
        'with flask_app.app.app_context():\n'
        '    out = {}\n'
        '    for s in scopes:\n'
        '        out[str(s)] = get_layout(branch_id=s)\n'
        '    print(json.dumps(out))\n'
    )
    r = subprocess.run([sys.executable, '-c', script, json.dumps(scopes)],
                        env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise RuntimeError('failed to record layouts via subprocess')
    out = json.loads(r.stdout.strip().splitlines()[-1])
    return {s: out[str(s)] for s in scopes}


def main(src):
    if not os.path.exists(src):
        print(f'FAIL: source DB not found: {src}')
        return 1
    dst = os.path.join('instance', '_print_layout_verify.db')
    shutil.copy2(src, dst)
    print(f'copied {src} -> {dst}')

    try:
        # `.env` also sets SQLALCHEMY_DATABASE_URI. python-dotenv's load_dotenv()
        # does NOT override an already-set environment variable, so this env wins
        # (same guard as tools/verify_r08_migration.py).
        env = dict(os.environ, SQLALCHEMY_DATABASE_URI=f'sqlite:///{os.path.abspath(dst)}')

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

        conn = sqlite3.connect(dst)
        legacy_schema_before = _print_layouts_schema(conn)
        legacy_count_before = conn.execute('select count(*) from print_layouts').fetchone()[0]
        branch_ids = [r[0] for r in conn.execute('select id from branches order by id').fetchall()]
        conn.close()
        print(f'branches in this DB: {branch_ids}')
        print(f'legacy print_layouts BEFORE: schema={legacy_schema_before!r} '
              f'rows={legacy_count_before}')

        # Every branch, plus the unscoped case (branch_id=None) -- "every branch"
        # per the brief, generalised to include the unscoped/default resolution
        # path too, since that is also a real printing path.
        scopes = [None] + branch_ids
        print(f'recording pre-migration layouts for scopes: {scopes}')
        before = _record_layouts(env, scopes)

        r = subprocess.run([sys.executable, '-m', 'flask', 'db', 'upgrade'],
                            env=env, capture_output=True, text=True)
        print(r.stdout, r.stderr)
        if r.returncode != 0:
            print('FAIL: flask db upgrade returned non-zero')
            return 1

        print(f'recording post-migration layouts for scopes: {scopes}')
        after = _record_layouts(env, scopes)

        failures = []
        for scope in scopes:
            label = 'unscoped' if scope is None else f'branch {scope}'
            b, a = before[scope], after[scope]
            if b == a:
                print(f'IDENTICAL for {label}')
            else:
                failures.append(f'{label}: get_layout() changed')
                print(f'DIFF for {label}:')
                print(f'  before: {json.dumps(b, sort_keys=True)}')
                print(f'  after:  {json.dumps(a, sort_keys=True)}')

        conn = sqlite3.connect(dst)
        named_count = conn.execute(
            "select count(*) from named_print_layouts where doc_type='purchase_orders'"
        ).fetchone()[0]
        legacy_schema_after = _print_layouts_schema(conn)
        legacy_count_after = conn.execute('select count(*) from print_layouts').fetchone()[0]
        conn.close()

        print(f'named_print_layouts rows created (doc_type=purchase_orders): {named_count}')
        if named_count == 0:
            failures.append('migration created zero named_print_layouts rows '
                             '(nothing was actually migrated -- check 1 passed for '
                             'the wrong reason)')

        if legacy_schema_after != legacy_schema_before:
            failures.append('legacy print_layouts SCHEMA changed')
            print(f'  schema before: {legacy_schema_before}')
            print(f'  schema after:  {legacy_schema_after}')
        else:
            print('legacy print_layouts schema: unchanged')

        if legacy_count_after != legacy_count_before:
            failures.append(f'legacy print_layouts ROW COUNT changed: '
                             f'{legacy_count_before} -> {legacy_count_after}')
        else:
            print(f'legacy print_layouts row count: unchanged ({legacy_count_after})')

        if failures:
            print('\nFAIL:')
            for f in failures:
                print('  -', f)
            return 1

        print('\nPASS -- get_layout() is byte-identical before and after prnlay_0002 '
              'for every branch and the unscoped case; legacy print_layouts table '
              'untouched (schema and row count).')
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
