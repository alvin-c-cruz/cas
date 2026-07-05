"""Task 4 — fail-closed BACKUP_* config."""


def test_backup_disabled_by_default(app):
    assert app.config['BACKUP_ENABLED'] is False
    assert app.config['BACKUP_STORAGE'] == 'local'
    assert app.config['BACKUP_STALE_HOURS'] == 30
    assert app.config['BACKUP_LOCK_TIMEOUT_MIN'] == 15
