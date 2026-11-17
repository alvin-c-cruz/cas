"""Remember me slides: a remembered sign-in lasts N days from the LAST visit, not from the sign-in (RM-1 B).

Owner, 13 Nov 2026, "RM-1 B" (work order 2026-11-13-remember-me-sliding). Before this the remember cookie lasted 7 days
from the sign-in, so a user who ticked the box was asked for her password again every week however often she used CAS.

Flask-Login's own REMEMBER_COOKIE_REFRESH_EACH_REQUEST is NOT used: in 0.6.3 it sets the cookie for every signed-in
user, ticked or not (`_update_remember_cookie` marks `_remember = "set"` whenever the session has a user), which would
make the box meaningless. CAS refreshes only a remember cookie the browser already sent, and only for the same user.
"""
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import pytest

pytestmark = [pytest.mark.users, pytest.mark.integration]

COOKIE = 'remember_token'


def _sign_in(client, username='admin', password='admin123', remember=True):
    data = {'username': username, 'password': password}
    if remember:
        data['remember_me'] = 'y'
    return client.post('/login', data=data)


def _remember_set_cookie(resp):
    """The Set-Cookie header for the remember cookie on *resp*, or None."""
    for header in resp.headers.getlist('Set-Cookie'):
        if header.startswith(COOKIE + '='):
            return header
    return None


def _expires(header):
    m = re.search(r'Expires=([^;]+)', header, re.I)
    assert m, header
    return parsedate_to_datetime(m.group(1))


def _is_deletion(header):
    return _expires(header).year <= 1970 or 'Max-Age=0' in header


@pytest.fixture
def later(monkeypatch):
    """Move Flask-Login's clock forward by *days* (it stamps Expires from datetime.utcnow())."""
    import flask_login.login_manager as lm

    def _move(days):
        real = datetime

        class _Later(real):
            @classmethod
            def utcnow(cls):
                return real.utcnow() + timedelta(days=days)
        monkeypatch.setattr(lm, 'datetime', _Later)
    return _move


class TestSliding:

    def test_a_ticked_sign_in_sets_the_cookie_for_7_days(self, client, admin_user, main_branch):
        header = _remember_set_cookie(_sign_in(client))
        assert header is not None
        left = _expires(header) - datetime.now(timezone.utc)
        assert timedelta(days=6, hours=23) < left <= timedelta(days=7, minutes=1)

    def test_each_visit_pushes_the_expiry_forward(self, client, admin_user, main_branch, later):
        first = _expires(_remember_set_cookie(_sign_in(client)))

        later(2)                                      # two days on, she opens CAS again
        resp = client.get('/login')                   # any request; signed in, so it redirects
        header = _remember_set_cookie(resp)

        assert header is not None, 'a remembered visit must re-issue the cookie'
        assert not _is_deletion(header)
        moved = _expires(header) - first
        assert timedelta(days=1, hours=23) < moved < timedelta(days=2, hours=1)

    def test_an_unticked_sign_in_never_gets_a_remember_cookie(self, client, admin_user, main_branch):
        assert _remember_set_cookie(_sign_in(client, remember=False)) is None
        for _ in range(2):
            assert _remember_set_cookie(client.get('/login')) is None
        assert client.get_cookie(COOKIE) is None

    @pytest.mark.parametrize('cookie_user,session_user,slides', [
        ('1', '1', True),       # her own cookie: slide it
        ('1', '2', False),      # someone else's cookie: never re-issue it under this user
        (None, '1', False),     # no cookie (box not ticked): nothing to slide
        ('1', None, False),     # nobody signed in on this session
    ])
    def test_the_hook_slides_only_the_signed_in_users_own_cookie(
            self, app, cookie_user, session_user, slides):
        """Unit check of the guard. (Through the screens, a browser remembered as A is sent past
        /login to A's dashboard, so B cannot sign in there without logging A out first.)"""
        from flask import Response, session
        from flask_login.utils import encode_cookie
        from app.users.remember import slide_remember_cookie
        headers = {}
        if cookie_user is not None:
            with app.test_request_context():
                headers['Cookie'] = f'{COOKIE}={encode_cookie(cookie_user)}'
        with app.test_request_context('/dashboard', headers=headers):
            if session_user is not None:
                session['_user_id'] = session_user
            slide_remember_cookie(Response())
            assert (session.get('_remember') == 'set') is slides

    def test_a_tampered_cookie_is_not_slid(self, app):
        from flask import Response, session
        from app.users.remember import slide_remember_cookie
        with app.test_request_context('/dashboard', headers={'Cookie': f'{COOKIE}=1|forged'}):
            session['_user_id'] = '1'
            slide_remember_cookie(Response())
            assert '_remember' not in session

    def test_logout_still_ends_it(self, client, admin_user, main_branch):
        _sign_in(client)
        resp = client.get('/logout')
        header = _remember_set_cookie(resp)
        assert header is not None and _is_deletion(header)
        assert _remember_set_cookie(client.get('/login')) is None

    def test_static_files_do_not_reissue_it(self, client, admin_user, main_branch):
        _sign_in(client)
        resp = client.get('/static/css/style.css')
        assert _remember_set_cookie(resp) is None


class TestDaysFromEnv:

    @pytest.mark.parametrize('raw,days', [
        (None, 7), ('', 7), ('  ', 7), ('0', 7), ('-3', 7), ('abc', 7), ('2.5', 7),
        ('14', 14), (' 30 ', 30), ('1', 1),
    ])
    def test_remember_cookie_days(self, monkeypatch, raw, days):
        import config
        if raw is None:
            monkeypatch.delenv('REMEMBER_COOKIE_DAYS', raising=False)
        else:
            monkeypatch.setenv('REMEMBER_COOKIE_DAYS', raw)
        assert config.remember_cookie_days() == days

    def test_the_config_uses_it(self):
        import config
        assert config.Config.REMEMBER_COOKIE_DURATION == timedelta(days=config.remember_cookie_days())
        assert not getattr(config.Config, 'REMEMBER_COOKIE_REFRESH_EACH_REQUEST', False), (
            "Flask-Login's flag remembers users who did not tick the box; CAS slides its own way")
