"""Unit tests for audit get_changes() normalization (BUG-AUDIT-DIFF-NOISE).

get_changes compared the raw model value (date/Decimal/int) against the
form-string new value, so unchanged typed fields registered as "changed" and
were logged as noisy old==new pairs. Both sides must be normalized the same way
(the way they are stored) before comparing.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.audit.utils import get_changes

pytestmark = [pytest.mark.unit, pytest.mark.audit]


def test_unchanged_date_is_not_reported():
    old = SimpleNamespace(due_date=date(2026, 6, 12))
    old_v, new_v = get_changes(old, {'due_date': '2026-06-12'}, ['due_date'])
    assert old_v == {} and new_v == {}, "a date equal to its ISO string must not count as changed"


def test_unchanged_decimal_is_not_reported():
    old = SimpleNamespace(amount=Decimal('100.00'))
    old_v, new_v = get_changes(old, {'amount': '100.00'}, ['amount'])
    assert old_v == {} and new_v == {}


def test_unchanged_int_is_not_reported():
    old = SimpleNamespace(qty=5)
    old_v, new_v = get_changes(old, {'qty': '5'}, ['qty'])
    assert old_v == {} and new_v == {}


def test_genuine_change_is_reported_normalized():
    old = SimpleNamespace(name='Acme Old', due_date=date(2026, 6, 12))
    old_v, new_v = get_changes(
        old, {'name': 'Acme New', 'due_date': '2026-07-01'}, ['name', 'due_date'])
    assert old_v == {'name': 'Acme Old', 'due_date': '2026-06-12'}
    assert new_v == {'name': 'Acme New', 'due_date': '2026-07-01'}


def test_bool_unchanged_and_changed():
    old = SimpleNamespace(is_active=True)
    # unchanged
    o1, n1 = get_changes(old, {'is_active': True}, ['is_active'])
    assert o1 == {} and n1 == {}
    # changed — booleans kept as booleans, not stringified
    o2, n2 = get_changes(old, {'is_active': False}, ['is_active'])
    assert o2 == {'is_active': True} and n2 == {'is_active': False}


def test_none_unchanged():
    old = SimpleNamespace(notes=None)
    o, n = get_changes(old, {'notes': None}, ['notes'])
    assert o == {} and n == {}
