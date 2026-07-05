"""Backup health signal. Keys on age-since-last-SUCCESS (a lingering 'running'
row or a 'failed' latest reads RED). Timestamps are stored naive-PHT, so they
are re-localized to PHT before any tz-aware subtraction."""
from app.utils import ph_now, PHT
from app.backup.models import BackupRun


def backup_health(clock=ph_now, stale_hours=30):
    latest = BackupRun.query.order_by(BackupRun.id.desc()).first()
    if latest is None:
        return {"state": "red", "reason": "no backup runs recorded",
                "last_success_at": None, "age_hours": None}

    last_success = (BackupRun.query.filter_by(status='success')
                    .order_by(BackupRun.id.desc()).first())
    if last_success is None:
        return {"state": "red",
                "reason": f"latest run {latest.status}, no successful backup",
                "last_success_at": None, "age_hours": None}

    stamp = last_success.verified_at or last_success.created_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=PHT)  # stored naive PHT -> tz-aware
    age = (clock() - stamp).total_seconds() / 3600.0

    if latest.status in ('failed', 'partial'):
        return {"state": "red", "reason": f"latest run {latest.status}",
                "last_success_at": stamp, "age_hours": age}
    if age > stale_hours:
        return {"state": "red",
                "reason": f"last success {age:.0f}h ago (> {stale_hours}h)",
                "last_success_at": stamp, "age_hours": age}
    return {"state": "green", "reason": "ok", "last_success_at": stamp, "age_hours": age}
