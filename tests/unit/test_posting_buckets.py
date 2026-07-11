"""Unit tests for the shared posting-bucket primitives (app/posting/buckets.py).

Pure, DB-free pins on the two behaviour-preserving primitives extracted in R4
Phase 1. They lock down each variant axis (reconcile trigger, largest-bucket
tie-break, negative guard, empty-bucket fallback, non-positive-line skip,
zero-amount test) so the AP/SI/CDV/CRV wrappers that follow can be repointed at
these primitives without changing any posted journal entry.

`Account` is faked with a tiny stand-in carrying only the `.id` / `.code`
attributes the primitives read -- the primitives never touch the ORM or the
session, which is exactly why they are unit-testable in isolation.
"""
from decimal import Decimal

import pytest

from app.posting.buckets import group_tax_buckets, reconcile_buckets_to_total

pytestmark = [pytest.mark.posting, pytest.mark.unit]


class FakeAccount:
    def __init__(self, id, code):
        self.id = id
        self.code = code

    def __repr__(self):
        return f"Acct({self.code})"


class FakeLine:
    def __init__(self, amount, account, line_total=None):
        self.amount = amount
        self.account = account
        self.line_total = line_total


def D(x):
    return Decimal(str(x))


# Reusable accounts (codes deliberately out of insertion order to prove sorting)
A_20301 = FakeAccount(3, '20301')
A_10241 = FakeAccount(1, '10241')
A_10242 = FakeAccount(2, '10242')
GT_POS = lambda amt: amt > 0        # AP/SI zero test
NE_ZERO = lambda amt: amt != 0      # CDV/CRV zero test


# --------------------------------------------------------------------------- #
# group_tax_buckets
# --------------------------------------------------------------------------- #
class TestGroupTaxBuckets:
    def test_groups_and_sorts_by_account_code(self):
        lines = [
            FakeLine('60.00', A_10242),
            FakeLine('40.00', A_10241),
            FakeLine('10.00', A_10242),
        ]
        out = group_tax_buckets(
            lines, amount_of=lambda l: l.amount, account_of=lambda l: l.account,
            amount_predicate=GT_POS, on_missing_account='skip')
        assert out == [(A_10241, D('40.00')), (A_10242, D('70.00'))]

    def test_falsy_amount_counts_as_zero_and_is_excluded(self):
        # amount None -> Decimal('0'); GT_POS(0) is False -> line dropped
        lines = [FakeLine(None, A_10241), FakeLine('25.00', A_10242)]
        out = group_tax_buckets(
            lines, amount_of=lambda l: l.amount, account_of=lambda l: l.account,
            amount_predicate=GT_POS, on_missing_account='skip')
        assert out == [(A_10242, D('25.00'))]

    def test_amount_predicate_gt_zero_vs_ne_zero(self):
        # A negative amount is kept under `!= 0` (CDV/CRV) but dropped under `> 0`.
        lines = [FakeLine('-5.00', A_10241)]
        assert group_tax_buckets(
            lines, amount_of=lambda l: l.amount, account_of=lambda l: l.account,
            amount_predicate=GT_POS, on_missing_account='skip') == []
        assert group_tax_buckets(
            lines, amount_of=lambda l: l.amount, account_of=lambda l: l.account,
            amount_predicate=NE_ZERO, on_missing_account='skip') == [(A_10241, D('-5.00'))]

    def test_line_skip_drops_non_positive_line_total(self):
        skip = lambda l: D(l.line_total) <= 0
        lines = [
            FakeLine('12.00', A_10241, line_total='100.00'),
            FakeLine('9.00', A_10242, line_total='-50.00'),  # skipped whole line
        ]
        out = group_tax_buckets(
            lines, amount_of=lambda l: l.amount, account_of=lambda l: l.account,
            amount_predicate=NE_ZERO, on_missing_account='skip', line_skip=skip)
        assert out == [(A_10241, D('12.00'))]

    def test_missing_account_skip_drops_the_line(self):
        lines = [FakeLine('7.00', None), FakeLine('3.00', A_10241)]
        out = group_tax_buckets(
            lines, amount_of=lambda l: l.amount, account_of=lambda l: l.account,
            amount_predicate=GT_POS, on_missing_account='skip')
        assert out == [(A_10241, D('3.00'))]

    def test_missing_account_callable_raises_with_message(self):
        lines = [FakeLine('7.00', None)]
        with pytest.raises(ValueError, match='no Input Tax account'):
            group_tax_buckets(
                lines, amount_of=lambda l: l.amount, account_of=lambda l: l.account,
                amount_predicate=GT_POS,
                on_missing_account=lambda l: "VAT category 'X' has no Input Tax account.")

    def test_empty_lines_returns_empty(self):
        assert group_tax_buckets(
            [], amount_of=lambda l: l.amount, account_of=lambda l: l.account,
            amount_predicate=GT_POS, on_missing_account='skip') == []


# --------------------------------------------------------------------------- #
# reconcile_buckets_to_total
# --------------------------------------------------------------------------- #
class TestReconcileBucketsToTotal:
    def test_only_if_false_skips_reconciliation_but_drops_zeros(self):
        buckets = [(A_10241, D('40.00')), (A_10242, D('0.00'))]
        out = reconcile_buckets_to_total(buckets, D('999.00'), only_if=False)
        assert out == [(A_10241, D('40.00'))]  # header ignored; zero dropped

    def test_no_diff_is_a_noop(self):
        buckets = [(A_10241, D('40.00')), (A_10242, D('60.00'))]
        out = reconcile_buckets_to_total(buckets, D('100.00'), only_if=True)
        assert out == buckets

    def test_positive_diff_absorbed_into_largest_by_amount(self):
        buckets = [(A_10241, D('40.00')), (A_10242, D('60.00'))]
        out = reconcile_buckets_to_total(buckets, D('105.00'), only_if=True,
                                         largest_by='amount')
        assert out == [(A_10241, D('40.00')), (A_10242, D('65.00'))]

    def test_largest_by_abs_picks_the_most_negative_bucket(self):
        # abs() variant: the -80 bucket is 'largest' by magnitude, absorbs the diff.
        buckets = [(A_10241, D('30.00')), (A_10242, D('-80.00'))]
        out = reconcile_buckets_to_total(buckets, D('-45.00'), only_if=True,
                                         largest_by='abs', allow_negative=True)
        # sum=-50, diff=-45-(-50)=+5 -> into -80 bucket -> -75
        assert out == [(A_10241, D('30.00')), (A_10242, D('-75.00'))]
        # by 'amount' (signed max) the +30 bucket would have absorbed it instead:
        out2 = reconcile_buckets_to_total(buckets, D('-45.00'), only_if=True,
                                          largest_by='amount', allow_negative=True)
        assert out2 == [(A_10241, D('35.00')), (A_10242, D('-80.00'))]

    def test_empty_buckets_with_fallback_books_the_whole_diff(self):
        out = reconcile_buckets_to_total([], D('75.00'), only_if=True,
                                         fallback_account=A_20301)
        assert out == [(A_20301, D('75.00'))]

    def test_empty_buckets_no_fallback_with_error_raises(self):
        with pytest.raises(ValueError, match='no expense line carries WHT'):
            reconcile_buckets_to_total(
                [], D('75.00'), only_if=True, fallback_account=None,
                empty_error='... no expense line carries WHT ...')

    def test_empty_buckets_no_fallback_no_error_is_silent_noop(self):
        # The VAT variant: empty + diff + no fallback + no error message -> [].
        assert reconcile_buckets_to_total(
            [], D('75.00'), only_if=True, fallback_account=None,
            empty_error=None) == []

    def test_negative_guard_raises_when_disallowed(self):
        # diff -50 overshoots the 40 bucket -> -10; guard raises.
        buckets = [(A_10241, D('40.00'))]
        with pytest.raises(ValueError, match='too far below'):
            reconcile_buckets_to_total(
                buckets, D('-10.00'), only_if=True, allow_negative=False,
                negative_error='override is too far below the computed VAT')

    def test_allow_negative_true_skips_the_guard(self):
        buckets = [(A_10241, D('40.00'))]
        out = reconcile_buckets_to_total(
            buckets, D('-10.00'), only_if=True, allow_negative=True)
        assert out == [(A_10241, D('-10.00'))]

    def test_reconcile_then_zero_bucket_is_dropped(self):
        # diff drives a bucket to exactly zero -> filtered out, not negative.
        buckets = [(A_10241, D('40.00')), (A_10242, D('60.00'))]
        out = reconcile_buckets_to_total(buckets, D('40.00'), only_if=True,
                                         largest_by='amount', allow_negative=False)
        # sum=100, diff=-60 -> into the 60 bucket -> 0 -> dropped
        assert out == [(A_10241, D('40.00'))]

    def test_input_iterable_is_not_mutated(self):
        buckets = [(A_10241, D('40.00'))]
        reconcile_buckets_to_total(buckets, D('50.00'), only_if=True)
        assert buckets == [(A_10241, D('40.00'))]
