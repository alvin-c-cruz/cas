"""Integration tests for Branch.theme_color create/edit wiring (R-11 #231)."""
import json
import pytest
from app.branches.models import Branch
from app.audit.models import AuditLog

pytestmark = [pytest.mark.branches, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestBranchThemeColorCreate:
    def test_checked_with_color_persists_hex(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/branches/create', data={
            'code': 'THMC1', 'name': 'Theme Create Branch', 'is_active': 'y',
            'use_custom_theme': 'y', 'theme_color': '#0ea5e9',
        }, follow_redirects=True)
        assert resp.status_code == 200

        branch = Branch.query.filter_by(code='THMC1').first()
        assert branch is not None
        assert branch.theme_color == '#0ea5e9'

    def test_unchecked_persists_null_even_with_a_color_present(self, client, db_session, admin_user, main_branch):
        login(client)
        client.post('/branches/create', data={
            'code': 'THMC2', 'name': 'Theme Create Branch Two', 'is_active': 'y',
            'theme_color': '#0ea5e9',  # checkbox omitted -> unchecked
        }, follow_redirects=True)

        branch = Branch.query.filter_by(code='THMC2').first()
        assert branch.theme_color is None

    def test_malformed_hex_is_rejected(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/branches/create', data={
            'code': 'THMC3', 'name': 'Theme Create Branch Three', 'is_active': 'y',
            'use_custom_theme': 'y', 'theme_color': 'not-a-color',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Branch.query.filter_by(code='THMC3').first() is None

    def test_create_audit_log_includes_theme_color(self, client, db_session, admin_user, main_branch):
        login(client)
        client.post('/branches/create', data={
            'code': 'THMC4', 'name': 'Theme Create Branch Four', 'is_active': 'y',
            'use_custom_theme': 'y', 'theme_color': '#22c55e',
        }, follow_redirects=True)

        branch = Branch.query.filter_by(code='THMC4').first()
        audit = AuditLog.query.filter_by(module='branch', action='create', record_id=branch.id).first()
        assert audit is not None
        assert json.loads(audit.new_values)['theme_color'] == '#22c55e'


class TestBranchThemeColorEdit:
    def test_edit_can_turn_theme_on(self, client, db_session, admin_user, main_branch):
        login(client)
        assert main_branch.theme_color is None
        resp = client.post(f'/branches/{main_branch.id}/edit', data={
            'code': main_branch.code, 'name': main_branch.name, 'is_active': 'y',
            'use_custom_theme': 'y', 'theme_color': '#8b5cf6',
        }, follow_redirects=True)
        assert resp.status_code == 200

        updated = db_session.get(Branch, main_branch.id)
        assert updated.theme_color == '#8b5cf6'

    def test_edit_can_turn_theme_off(self, client, db_session, admin_user, main_branch):
        main_branch.theme_color = '#8b5cf6'
        db_session.commit()

        login(client)
        client.post(f'/branches/{main_branch.id}/edit', data={
            'code': main_branch.code, 'name': main_branch.name, 'is_active': 'y',
            # use_custom_theme omitted -> unchecked -> forced NULL
            'theme_color': '#8b5cf6',
        }, follow_redirects=True)

        updated = db_session.get(Branch, main_branch.id)
        assert updated.theme_color is None

    def test_edit_audit_log_includes_theme_color(self, client, db_session, admin_user, main_branch):
        login(client)
        client.post(f'/branches/{main_branch.id}/edit', data={
            'code': main_branch.code, 'name': main_branch.name, 'is_active': 'y',
            'use_custom_theme': 'y', 'theme_color': '#f59e0b',
        }, follow_redirects=True)

        audit = AuditLog.query.filter_by(module='branch', action='update', record_id=main_branch.id).first()
        assert audit is not None
        assert json.loads(audit.new_values)['theme_color'] == '#f59e0b'
