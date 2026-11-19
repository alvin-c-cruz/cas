"""An administrator can set a new password for another user from the Edit User page (ADMIN-RESET A).

Owner, 14 Nov 2026: "ADMIN-RESET A" (work order 2026-11-14-admin-reset-password-on-edit-user). PW-3's view code
already set the password, but users/form.html showed the fields only `{% if not user %}` (creating), and user creation
has since been removed, so no screen offered them: the admin of RIC could not reset China Mae's password and had to use
the console. These tests GET the page and look for the fields, so the screen and the route can't drift apart again
(memory `verify-screen-path-in-template`).

PW-3's rules are kept: the 12-character policy, `must_change_password` set, the lockout cleared, an audit row; no
password is ever shown, logged or echoed back into the form.
"""
import re
from datetime import timedelta

import pytest

from app import db
from app.audit.models import AuditLog
from app.utils import ph_now

pytestmark = [pytest.mark.integration, pytest.mark.users]

NEW = 'Brand-New#Pass2026'


def _login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _payload(main_branch, **overrides):
    data = {'username': 'staff', 'email': 'staff@test.com', 'full_name': 'Staff User',
            'role': 'staff', 'branch_ids': [str(main_branch.id)], 'is_active': 'y'}
    data.update(overrides)
    return data


def _inputs(html, name):
    return re.findall(r'<input[^>]*name="%s"[^>]*>' % name, html)


class TestThePageOffersIt:

    def test_editing_another_user_shows_the_password_pair(self, client, admin_user, staff_user, main_branch):
        _login(client, 'admin', 'admin123')
        html = client.get(f'/users/{staff_user.id}/edit').data.decode('utf-8')
        assert len(_inputs(html, 'password')) == 1
        assert len(_inputs(html, 'confirm_password')) == 1
        assert 'Set a new password' in html
        assert 'Leave both blank to keep the current password' in html

    def test_editing_your_own_record_does_not(self, client, admin_user, main_branch):
        _login(client, 'admin', 'admin123')
        html = client.get(f'/users/{admin_user.id}/edit').data.decode('utf-8')
        assert _inputs(html, 'password') == [] and _inputs(html, 'confirm_password') == []
        assert 'Set a new password' not in html


class TestSettingIt:

    def test_a_new_password_is_set_flagged_audited_and_the_lockout_cleared(
            self, client, db_session, admin_user, staff_user, main_branch):
        staff_user.failed_login_attempts = 5
        staff_user.account_locked_until = ph_now() + timedelta(minutes=15)
        db_session.commit()
        assert staff_user.is_account_locked(), 'anti-vacuity: the user must start locked'
        _login(client, 'admin', 'admin123')

        client.post(f'/users/{staff_user.id}/edit',
                    data=_payload(main_branch, password=NEW, confirm_password=NEW), follow_redirects=True)

        db_session.refresh(staff_user)
        assert staff_user.check_password(NEW)
        assert staff_user.must_change_password is True
        assert not staff_user.is_account_locked()
        assert staff_user.failed_login_attempts == 0
        rows = AuditLog.query.filter_by(module='user', action='password_reset', record_id=staff_user.id).all()
        assert len(rows) == 1
        assert NEW not in (rows[0].notes or '') and NEW not in str(rows[0].new_values or '')

    def test_the_user_can_then_sign_in_and_is_sent_to_change_password(
            self, client, admin_user, staff_user, main_branch):
        _login(client, 'admin', 'admin123')
        client.post(f'/users/{staff_user.id}/edit',
                    data=_payload(main_branch, password=NEW, confirm_password=NEW), follow_redirects=True)
        client.get('/logout', follow_redirects=True)
        _login(client, 'staff', NEW)
        resp = client.get('/dashboard')
        assert resp.status_code == 302 and '/profile/change-password' in resp.headers['Location']

    def test_blank_keeps_the_current_password(self, client, db_session, admin_user, staff_user, main_branch):
        before = staff_user.password_hash
        _login(client, 'admin', 'admin123')
        client.post(f'/users/{staff_user.id}/edit', data=_payload(main_branch, full_name='Staff Renamed'),
                    follow_redirects=True)
        db_session.refresh(staff_user)
        assert staff_user.full_name == 'Staff Renamed', 'anti-vacuity: the save went through'
        assert staff_user.password_hash == before
        assert not staff_user.must_change_password


class TestRefusals:

    @pytest.mark.parametrize('confirm', ['', 'Brand-New#Pass2027'])
    def test_a_missing_or_different_confirmation_is_refused(
            self, client, db_session, admin_user, staff_user, main_branch, confirm):
        before = staff_user.password_hash
        _login(client, 'admin', 'admin123')
        resp = client.post(f'/users/{staff_user.id}/edit',
                           data=_payload(main_branch, password=NEW, confirm_password=confirm))
        db_session.refresh(staff_user)
        assert staff_user.password_hash == before
        assert 'Passwords must match.' in resp.data.decode('utf-8')

    def test_the_12_character_policy_applies(self, client, db_session, admin_user, staff_user, main_branch):
        before = staff_user.password_hash
        _login(client, 'admin', 'admin123')
        client.post(f'/users/{staff_user.id}/edit',
                    data=_payload(main_branch, password='Short#1', confirm_password='Short#1'))
        db_session.refresh(staff_user)
        assert staff_user.password_hash == before

    def test_a_refused_save_never_echoes_the_password(self, client, admin_user, staff_user, main_branch):
        _login(client, 'admin', 'admin123')
        html = client.post(f'/users/{staff_user.id}/edit',
                           data=_payload(main_branch, password=NEW, confirm_password='')).data.decode('utf-8')
        assert NEW not in html
        for tag in _inputs(html, 'password') + _inputs(html, 'confirm_password'):
            assert 'value="' not in tag or 'value=""' in tag
