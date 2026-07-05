"""Backup CLI commands. `backup-run` is what PythonAnywhere's scheduler calls
once premium is paid; `backup-verify` proves the latest artifact restorable;
`backup-restore` decrypts to a scratch path (never the live DB)."""
import json
import os
import tempfile

import click
from flask import current_app
from flask.cli import with_appcontext

from app import db
from app.backup.service import run_backup, verify_latest


@click.command('backup-run')
@with_appcontext
def backup_run_cmd():
    run = run_backup('cli', 'system', config=current_app.config)
    click.echo(f"backup {run.status} (run {run.id}) {run.error_message or ''}".strip())
    raise SystemExit(0 if run.status == 'success' else 1)


@click.command('backup-verify')
@with_appcontext
def backup_verify_cmd():
    res = verify_latest(config=current_app.config)
    click.echo(f"verify ok={res['ok']} {res['checks']}")
    raise SystemExit(0 if res['ok'] else 1)


@click.command('backup-restore')
@click.option('--into', required=True, help='scratch path to restore into (never the live DB)')
@click.option('--run-id', type=int, default=None, help='specific BackupRun id (default: latest success)')
@with_appcontext
def backup_restore_cmd(into, run_id):
    from app.backup.models import BackupRun
    from app.backup.storage import get_storage
    from app.backup.crypto import FileKeyProvider, decrypt

    live = os.path.abspath(db.engine.url.database)
    if os.path.abspath(into) == live:
        raise click.ClickException('refusing to restore over the live DB; choose a scratch --into')

    if run_id:
        run = db.session.get(BackupRun, run_id)
    else:
        run = (BackupRun.query.filter_by(status='success')
               .order_by(BackupRun.id.desc()).first())
    if run is None or run.status != 'success':
        raise click.ClickException('no successful backup to restore')

    storage = get_storage(current_app.config)
    kp = FileKeyProvider(current_app.config['BACKUP_ENC_KEY'])
    arts = json.loads(run.artifacts)
    db_entry = next(v for k, v in arts.items() if k.endswith('.db.enc'))

    tmp = os.path.join(tempfile.mkdtemp(prefix='casrst-'), 'a.enc')
    try:
        storage.get(db_entry['ref'], tmp)
        with open(tmp, 'rb') as fh:
            plain = decrypt(fh.read(), kp)
        with open(into, 'wb') as fh:
            fh.write(plain)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
        os.rmdir(os.path.dirname(tmp))
    click.echo(f"restored run {run.id} -> {into}")
