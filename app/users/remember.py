"""Remember me slides: N days from the user's last visit, not from the sign-in (RM-1 B, owner 13 Nov 2026).

Work order: products/cas/app-docs/bug-reports/2026-11-13-remember-me-sliding.md.

Flask-Login stamps the remember cookie once, at sign-in, so a user who ticked "Remember me" was asked for her password
again every 7 days however often she used CAS (Philgen's angilyn: sign-ins 7 days apart, Aug to Nov 2026).

Flask-Login's own switch for this, REMEMBER_COOKIE_REFRESH_EACH_REQUEST, is not used: in 0.6.3 its after-request hook
marks the cookie to be set whenever the session holds a user, so every signed-in user would leave with a remember
cookie, ticked or not. This hook re-issues the cookie only when:
- the browser sent one,
- it is valid and names the user this session is signed in as, and
- nothing in this request already decided the cookie's fate (sign-in sets it, logout clears it).

It runs BEFORE Flask-Login's `_update_remember_cookie` (Flask runs after-request hooks in reverse registration order,
and create_app registers this after `login_manager.init_app`), which then writes the cookie with a fresh expiry.
"""
from flask import current_app, request, session
from flask_login.utils import decode_cookie


def slide_remember_cookie(response):
    if request.endpoint == 'static' or '_remember' in session:
        return response
    user_id = session.get('_user_id')
    if user_id is None:
        return response
    cookie = request.cookies.get(current_app.config.get('REMEMBER_COOKIE_NAME', 'remember_token'))
    if cookie and decode_cookie(cookie) == str(user_id):
        session['_remember'] = 'set'
    return response
