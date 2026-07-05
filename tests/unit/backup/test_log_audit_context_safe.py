"""Task 0 — log_audit must write a row when called outside a request context
(e.g. a CLI/scheduler backup run), honoring the explicit user_id param."""
from app.audit.models import AuditLog
from app.audit.utils import log_audit


def test_log_audit_outside_request_context_writes_row(db_session, admin_user):
    # No request context — simulate a CLI/scheduler call.
    entry = log_audit(module='backup', action='run', record_id=1,
                      record_identifier='2026-07-05T00:00:00', user_id=admin_user.id)
    assert entry is not None
    row = db_session.get(AuditLog, entry.id)
    assert row.module == 'backup'
    assert row.user_id == admin_user.id
    assert row.ip_address is None  # no request -> no IP, but no crash


def test_log_audit_outside_request_context_without_user_id(db_session):
    # No user_id and no request context -> must not touch current_user and crash.
    entry = log_audit(module='backup', action='run', record_id=2,
                      record_identifier='cli run')
    assert entry is not None
    assert db_session.get(AuditLog, entry.id).user_id is None
