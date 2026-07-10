"""The tie-out gate.

Entries import already POSTED and CAS has no journal-entry edit route, so the
tie-out is not advisory -- `--commit` is refused unless it passes. It compares the
legacy books against what CAS actually holds at three granularities, because each
catches a different class of error:

  * grand total     -- catches wholesale loss (a book that never ran)
  * per account     -- catches a bad account map (debits landing on the wrong code)
  * per account+month -- catches date corruption (right totals, wrong periods)

A balanced-but-wrong import passes the first check and fails the others, which is
exactly the `posted-je-leg-vs-source-header` lesson: Dr == Cr proves nothing.
"""
from decimal import Decimal

import pytest

from scripts.legacy_import.tieout import Discrepancy, compare_totals, tieout_passed

pytestmark = [pytest.mark.unit, pytest.mark.legacy_import]

D = Decimal


def test_identical_books_tie_out():
    expected = {(1, 2023, 1): (D('100.00'), D('100.00'))}
    assert compare_totals(expected, dict(expected)) == []
    assert tieout_passed([]) is True


def test_missing_key_in_cas_is_reported():
    expected = {(1, 2023, 1): (D('100.00'), D('100.00'))}
    (issue,) = compare_totals(expected, {})
    assert isinstance(issue, Discrepancy)
    assert issue.key == (1, 2023, 1)
    assert issue.actual == (D('0.00'), D('0.00'))
    assert 'missing' in issue.reason


def test_extra_key_in_cas_is_reported():
    """CAS holding a bucket the legacy books never had is just as wrong."""
    actual = {(9, 2023, 1): (D('5.00'), D('5.00'))}
    (issue,) = compare_totals({}, actual)
    assert issue.key == (9, 2023, 1)
    assert issue.expected == (D('0.00'), D('0.00'))
    assert 'unexpected' in issue.reason


def test_a_balanced_but_wrong_amount_is_caught():
    """Dr == Cr on both sides, yet the amounts differ -- balance proves nothing."""
    expected = {(1, 2023, 1): (D('100.00'), D('100.00'))}
    actual = {(1, 2023, 1): (D('110.00'), D('110.00'))}
    (issue,) = compare_totals(expected, actual)
    assert issue.expected == (D('100.00'), D('100.00'))
    assert issue.actual == (D('110.00'), D('110.00'))


def test_amounts_moved_to_the_wrong_account_are_caught():
    """Grand totals agree; the account map sent the debit to the wrong code."""
    expected = {(1, 2023, 1): (D('100.00'), D('0.00')),
                (2, 2023, 1): (D('0.00'), D('100.00'))}
    actual = {(3, 2023, 1): (D('100.00'), D('0.00')),
              (2, 2023, 1): (D('0.00'), D('100.00'))}
    issues = compare_totals(expected, actual)
    keys = sorted(i.key for i in issues)
    assert keys == [(1, 2023, 1), (3, 2023, 1)]


def test_amounts_moved_to_the_wrong_month_are_caught():
    """Per-account totals agree; the dates were corrupted."""
    expected = {(1, 2023, 1): (D('100.00'), D('0.00'))}
    actual = {(1, 2023, 2): (D('100.00'), D('0.00'))}
    issues = compare_totals(expected, actual)
    assert len(issues) == 2
    assert tieout_passed(issues) is False


def test_a_one_centavo_drift_is_caught():
    expected = {(1, 2023, 1): (D('100.00'), D('100.00'))}
    actual = {(1, 2023, 1): (D('100.01'), D('100.00'))}
    assert compare_totals(expected, actual) != []


def test_discrepancies_are_sorted_for_a_stable_report():
    expected = {(2, 2023, 1): (D('1.00'), D('0.00')),
                (1, 2023, 1): (D('1.00'), D('0.00'))}
    issues = compare_totals(expected, {})
    assert [i.key for i in issues] == [(1, 2023, 1), (2, 2023, 1)]
