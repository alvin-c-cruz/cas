from datetime import date
import pytest
from app.utils import end_of_month

pytestmark = [pytest.mark.unit]


def test_end_of_month_31_day_month():
    assert end_of_month(date(2026, 7, 8)) == date(2026, 7, 31)


def test_end_of_month_february_non_leap():
    assert end_of_month(date(2026, 2, 10)) == date(2026, 2, 28)


def test_end_of_month_february_leap():
    assert end_of_month(date(2028, 2, 10)) == date(2028, 2, 29)


def test_end_of_month_december():
    assert end_of_month(date(2026, 12, 1)) == date(2026, 12, 31)


def test_end_of_month_idempotent_on_month_end():
    assert end_of_month(date(2026, 7, 31)) == date(2026, 7, 31)
