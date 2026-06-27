import pytest
from app.settings import AppSettings
from app.users.utils import accountant_self_approval_enabled

pytestmark = [pytest.mark.unit]


def test_self_approval_off_by_default(db_session):
    assert accountant_self_approval_enabled() is False  # no row → default '0'


def test_self_approval_on_when_set_to_1(db_session):
    AppSettings.set_setting('accountant_email_self_approval', '1')
    assert accountant_self_approval_enabled() is True


def test_self_approval_off_when_set_to_0(db_session):
    AppSettings.set_setting('accountant_email_self_approval', '0')
    assert accountant_self_approval_enabled() is False
