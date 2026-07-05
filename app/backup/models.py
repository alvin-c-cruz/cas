"""BackupRun — one row per backup attempt. Metadata only (no filenames /
entity data). Success means verified-landed (see service.run_backup)."""
from app import db
from app.utils import ph_now


class BackupRun(db.Model):
    __tablename__ = 'backup_runs'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    started_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    finished_at = db.Column(db.DateTime)
    triggered_by = db.Column(db.String(16), nullable=False)   # manual|cli|scheduled
    actor = db.Column(db.String(80))
    status = db.Column(db.String(16), nullable=False)         # running|success|failed|partial
    db_plaintext_sha256 = db.Column(db.String(64))
    db_size = db.Column(db.Integer)
    artifacts = db.Column(db.Text)                            # JSON mirror of manifest artifacts
    manifest_sha256 = db.Column(db.String(64))
    key_id = db.Column(db.String(16))
    verified_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)
    duration_ms = db.Column(db.Integer)

    def __repr__(self):
        return f'<BackupRun {self.id} {self.status} {self.created_at}>'
