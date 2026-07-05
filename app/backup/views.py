"""Backup admin views: status page + run button. Admin-gated."""
from flask import Blueprint, render_template, redirect, url_for, flash, current_app
from flask_login import current_user

from app.users.views import admin_required
from app.backup.health import backup_health
from app.backup.models import BackupRun
from app.backup.service import run_backup

backup_bp = Blueprint('backup', __name__, template_folder='templates')


@backup_bp.route('/backup')
@admin_required
def status():
    health = backup_health(stale_hours=current_app.config['BACKUP_STALE_HOURS'])
    runs = BackupRun.query.order_by(BackupRun.id.desc()).limit(20).all()
    return render_template('backup/status.html', health=health, runs=runs)


@backup_bp.route('/backup/run', methods=['POST'])
@admin_required
def run_now():
    if not current_app.config.get('BACKUP_ENABLED'):
        flash('Backup is not configured on this instance.', 'error')
        return redirect(url_for('backup.status'))
    run = run_backup('manual', current_user.username, config=current_app.config)
    if run.status == 'success':
        flash('Backup completed and verified.', 'success')
    else:
        flash(f'Backup {run.status}: {run.error_message or "see log"}', 'error')
    return redirect(url_for('backup.status'))
