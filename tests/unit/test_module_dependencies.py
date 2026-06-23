import pytest

pytestmark = [pytest.mark.unit]

CATALOG = [
    {'key': 'a', 'optional': True, 'depends_on': []},
    {'key': 'b', 'optional': True, 'depends_on': ['a']},
]


def test_enable_blocked_when_prereq_off():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('b', True, enabled_keys=set(), registry=CATALOG)
    assert ok is False and 'a' in reason


def test_enable_allowed_when_prereq_on():
    from app.users.module_access import can_toggle
    ok, _ = can_toggle('b', True, enabled_keys={'a'}, registry=CATALOG)
    assert ok is True


def test_disable_blocked_when_dependent_enabled():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('a', False, enabled_keys={'a', 'b'}, registry=CATALOG)
    assert ok is False and 'b' in reason


def test_disable_allowed_when_no_dependent():
    from app.users.module_access import can_toggle
    ok, _ = can_toggle('a', False, enabled_keys={'a'}, registry=CATALOG)
    assert ok is True
