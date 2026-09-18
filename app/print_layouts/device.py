"""Identify the WORKSTATION, not the user.

A layout belongs to a printer and a workstation prints to one printer, so the
machine is the right thing to remember a layout choice against. The cookie holds
only an opaque id; the choice itself is a server-side row, so an admin can see
what each machine is set to and a cleared cookie degrades to the default rather
than to something wrong.

Deliberately NOT company-scoped, unlike cas_philgen / cas_ric: philgen and ric on
one machine are the same physical printer, and the pref rows live in each
company's own database, so nothing leaks.
"""
import uuid

from flask import request

DEVICE_COOKIE = 'cas_device_id'
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 5   # five years; a desk outlives a session


def current_device_id():
    """This workstation's id, or None when the cookie is absent or malformed."""
    raw = (request.cookies.get(DEVICE_COOKIE) or '').strip()
    return raw if raw and len(raw) <= 64 else None


def new_device_id():
    return uuid.uuid4().hex


def attach_device_cookie(response):
    """Issue an id to a workstation that has none. Registered as an after_request."""
    if current_device_id() is not None:
        return response
    if request.cookies.get(DEVICE_COOKIE) is not None:
        pass   # present but malformed -- reissue
    response.set_cookie(
        DEVICE_COOKIE, new_device_id(),
        max_age=DEVICE_COOKIE_MAX_AGE, httponly=True, samesite='Lax',
        secure=bool(request.is_secure),
    )
    return response
