"""The workstation is a cookie. Absent or cleared must degrade, never fail."""
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
