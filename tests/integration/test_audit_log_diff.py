"""Audit-log UI must show before→after for UPDATE entries (BUG-V-04).

`log_update` persists both old_values and new_values, but the audit-log page
previously rendered only the new state. These tests assert the OLD value is
also surfaced for updates, and that creates (no old) still render cleanly.
"""
import json

import pytest

from app.audit.models import AuditLog
from app.utils import ph_now

pytestmark = [pytest.mark.audit, pytest.mark.integration]


def _login_admin(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


class TestAuditLogDiff:
    def test_update_entry_shows_old_and_new(self, client, db_session, admin_user, main_branch):
        db_session.add(AuditLog(
            module='vendor', action='update', record_id=1,
            record_identifier='V001 - Acme', user_id=admin_user.id,
            branch_id=main_branch.id, timestamp=ph_now(),
            old_values=json.dumps({'name': 'Acme OLDNAME'}),
            new_values=json.dumps({'name': 'Acme NEWNAME'}),
        ))
        db_session.commit()
        _login_admin(client)

        resp = client.get('/audit-log')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'Acme NEWNAME' in body
        assert 'Acme OLDNAME' in body, \
            "audit UI must show the OLD value for an update, not just the new (BUG-V-04)"

    def test_create_entry_renders_new_only(self, client, db_session, admin_user, main_branch):
        """A create (no old_values) still renders its new values without error."""
        db_session.add(AuditLog(
            module='vendor', action='create', record_id=2,
            record_identifier='V002 - Beta', user_id=admin_user.id,
            branch_id=main_branch.id, timestamp=ph_now(),
            old_values=None,
            new_values=json.dumps({'name': 'Beta CREATED'}),
        ))
        db_session.commit()
        _login_admin(client)

        resp = client.get('/audit-log')
        assert resp.status_code == 200
        assert 'Beta CREATED' in resp.data.decode()
