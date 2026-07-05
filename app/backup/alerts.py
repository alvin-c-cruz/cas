"""Loud failure/staleness signal. CAS has no email, so a RED backup health
state raises an in-app Notification for every admin."""
from app import db
from app.users.models import User
from app.notifications.models import Notification
from app.backup.health import backup_health


def notify_if_stale(stale_hours=30):
    health = backup_health(stale_hours=stale_hours)
    if health['state'] != 'red':
        return 0
    admins = User.query.filter_by(role='admin', is_active=True).all()
    for admin in admins:
        db.session.add(Notification(
            user_id=admin.id, title="Backup problem",
            message=f"Backup health RED: {health['reason']}", category='error',
            related_type='backup', related_id=None))
    db.session.commit()
    return len(admins)
