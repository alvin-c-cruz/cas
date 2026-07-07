"""`flask integrity-check` -- headless data-integrity gate for the /deploy skill.

Exit code 0 = all findings ok; 1 = any violation. Flags:
  --json                     machine-readable output
  --dump-aggregates PATH     write current aggregates to PATH and exit 0
  --compare-aggregates PATH  load a baseline; run checks + aggregate drift; exit 1 on any failure
"""
import json as _json

import click
from flask.cli import with_appcontext

from app import db
from app.integrity.checks import run_checks, compute_aggregates, compare_aggregates


@click.command('integrity-check')
@click.option('--json', 'as_json', is_flag=True, help='Machine-readable JSON output.')
@click.option('--dump-aggregates', 'dump_path', type=click.Path(), default=None,
              help='Write current aggregates to PATH and exit 0.')
@click.option('--compare-aggregates', 'compare_path', type=click.Path(exists=True), default=None,
              help='Load a baseline aggregates file; run checks + drift; exit 1 on any failure.')
@with_appcontext
def integrity_check_cmd(as_json, dump_path, compare_path):
    session = db.session
    if dump_path:
        with open(dump_path, 'w', encoding='utf-8') as fh:
            _json.dump(compute_aggregates(session), fh, indent=2)
        click.echo(f'aggregates written to {dump_path}')
        return
    findings = run_checks(session)
    if compare_path:
        with open(compare_path, encoding='utf-8') as fh:
            before = _json.load(fh)
        findings += compare_aggregates(before, compute_aggregates(session))
    ok = all(f['ok'] for f in findings)
    if as_json:
        click.echo(_json.dumps({'ok': ok, 'findings': findings}, indent=2))
    else:
        for f in findings:
            click.echo(f"[{'OK ' if f['ok'] else 'BAD'}] {f['check']}: {f['detail']}")
        click.echo('INTEGRITY OK' if ok else 'INTEGRITY FAILED')
    raise SystemExit(0 if ok else 1)
