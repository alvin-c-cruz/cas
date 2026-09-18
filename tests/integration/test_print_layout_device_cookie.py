"""The workstation is a cookie. Absent or cleared must degrade, never fail."""
import uuid

import pytest
from app.print_layouts.device import DEVICE_COOKIE, current_device_id

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def test_a_first_visit_is_issued_a_device_id(client):
    resp = client.get('/login')
    assert resp.status_code == 200
    assert client.get_cookie(DEVICE_COOKIE) is not None, 'no device cookie set'


def test_the_device_id_is_stable_across_requests(client):
    client.get('/login')
    first = client.get_cookie(DEVICE_COOKIE).value
    client.get('/login')
    second = client.get_cookie(DEVICE_COOKIE).value
    assert first == second, 'a new id per request would make the pref unfindable'


def test_no_cookie_reads_as_none_rather_than_raising(app):
    with app.test_request_context('/'):
        assert current_device_id() is None


def test_a_non_html_response_does_not_carry_the_device_cookie(client):
    """A concurrent asset/XHR response must never propose a competing device id --
    only the page's single HTML response may. Otherwise a fresh device could be handed
    two different ids in one page load, and Task 5's per-device preference row would be
    keyed to whichever one the browser didn't keep."""
    static_resp = client.get('/static/favicon.svg')
    assert static_resp.status_code == 200
    assert static_resp.mimetype != 'text/html'
    assert client.get_cookie(DEVICE_COOKIE) is None, \
        'a non-HTML response set the device cookie'

    html_resp = client.get('/login')
    assert html_resp.mimetype == 'text/html'
    assert client.get_cookie(DEVICE_COOKIE) is not None, \
        'the guard disabled the feature outright -- HTML responses must still get one'


def test_an_oversized_cookie_value_is_rejected(app):
    with app.test_request_context('/', headers={'Cookie': f'{DEVICE_COOKIE}=' + 'x' * 65}):
        assert current_device_id() is None


def test_an_oversized_cookie_is_healed_on_the_next_html_response(client):
    """A junk cookie must not leave the workstation broken forever -- the next HTML
    response reissues a fresh, valid id."""
    junk = 'x' * 65
    client.set_cookie(DEVICE_COOKIE, junk)
    resp = client.get('/login')
    assert resp.status_code == 200
    healed = client.get_cookie(DEVICE_COOKIE)
    assert healed is not None
    assert healed.value != junk
    assert len(healed.value) <= 64


def test_a_whitespace_only_cookie_value_is_rejected(app):
    with app.test_request_context('/', headers={'Cookie': f'{DEVICE_COOKIE}="   "'}):
        assert current_device_id() is None


def test_a_whitespace_only_cookie_is_healed_on_the_next_html_response(client):
    client.set_cookie(DEVICE_COOKIE, '   ')
    resp = client.get('/login')
    assert resp.status_code == 200
    healed = client.get_cookie(DEVICE_COOKIE)
    assert healed is not None
    assert healed.value.strip() != ''
    assert len(healed.value) <= 64


def test_a_well_formed_device_id_is_accepted_unchanged(app):
    """Contrast for the two rejection tests above -- a validator that rejected
    everything would also pass them."""
    valid = uuid.uuid4().hex
    with app.test_request_context('/', headers={'Cookie': f'{DEVICE_COOKIE}={valid}'}):
        assert current_device_id() == valid
