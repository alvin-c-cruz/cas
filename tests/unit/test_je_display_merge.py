"""The voucher JE face sums legs hitting the same account on the same side.

Owner, 2026-09-09. The rule is PER SIDE and NEVER NETTED: an account carrying
both a debit and a credit keeps both rows, because netting would make the
printed totals disagree with the posted entry and the face would stop tying to
the books.
"""
from decimal import Decimal

import pytest

from app.common.je_display import (merge_same_account_lines,
                                   merge_same_account_rows)

pytestmark = [pytest.mark.unit]


class _Account:
    def __init__(self, code, name):
        self.code, self.name = code, name


class _Leg:
    """Shaped like a JournalEntryLine as the templates read it."""

    def __init__(self, account_id, account, debit=None, credit=None):
        self.account_id, self.account = account_id, account
        self.debit_amount = debit
        self.credit_amount = credit


FREIGHT = _Account('5010', 'Freight')
SUPPLIES = _Account('5020', 'Supplies')
PAYABLE = _Account('2010', 'Accounts Payable')


def test_two_debits_on_one_account_become_one_row():
    rows = merge_same_account_lines([
        _Leg(1, FREIGHT, debit=Decimal('1000.00')),
        _Leg(1, FREIGHT, debit=Decimal('1500.00')),
    ])
    assert len(rows) == 1
    assert rows[0].account is FREIGHT
    assert rows[0].debit_amount == Decimal('2500.00')
    assert rows[0].merged_count == 2


def test_a_different_account_is_not_swept_in():
    """Control: merging must key on the ACCOUNT, not merge everything on a side."""
    rows = merge_same_account_lines([
        _Leg(1, FREIGHT, debit=Decimal('1000.00')),
        _Leg(2, SUPPLIES, debit=Decimal('800.00')),
    ])
    assert [r.debit_amount for r in rows] == [Decimal('1000.00'), Decimal('800.00')]


def test_the_same_account_on_both_sides_keeps_both_rows():
    """The owner's decision, and the reason for it: netting these two into one
    3,300 credit would print Dr 3,800 / Cr 3,800 against a posted entry of
    Dr 4,300 / Cr 4,300."""
    rows = merge_same_account_lines([
        _Leg(3, PAYABLE, debit=Decimal('500.00')),
        _Leg(3, PAYABLE, credit=Decimal('3800.00')),
    ])
    assert len(rows) == 2
    assert rows[0].debit_amount == Decimal('500.00')
    assert rows[1].credit_amount == Decimal('3800.00')


def test_the_totals_are_unchanged_by_merging():
    """The invariant that lets this be a display-only change: because merging
    only ever combines within a side, an entry that tied before still ties."""
    legs = [
        _Leg(1, FREIGHT, debit=Decimal('1000.00')),
        _Leg(1, FREIGHT, debit=Decimal('1500.00')),
        _Leg(2, SUPPLIES, debit=Decimal('800.00')),
        _Leg(3, PAYABLE, credit=Decimal('3300.00')),
    ]
    rows = merge_same_account_lines(legs)
    before_d = sum(Decimal(str(l.debit_amount or 0)) for l in legs)
    before_c = sum(Decimal(str(l.credit_amount or 0)) for l in legs)
    after_d = sum(Decimal(str(r.debit_amount or 0)) for r in rows)
    after_c = sum(Decimal(str(r.credit_amount or 0)) for r in rows)
    assert (before_d, before_c) == (after_d, after_c) == (Decimal('3300.00'),
                                                          Decimal('3300.00'))


def test_first_appearance_order_is_kept():
    """The caller sorts non-VAT debits -> VAT debits -> credits before calling
    this. A merged row must sit where its FIRST leg sat or that sort is lost."""
    rows = merge_same_account_lines([
        _Leg(2, SUPPLIES, debit=Decimal('800.00')),
        _Leg(1, FREIGHT, debit=Decimal('1000.00')),
        _Leg(2, SUPPLIES, debit=Decimal('200.00')),
    ])
    assert [r.account.code for r in rows] == ['5020', '5010']
    assert rows[0].debit_amount == Decimal('1000.00')


def test_the_source_legs_are_not_mutated():
    """The posted entry is permanent. If merging wrote back onto the ORM legs,
    the next commit in the request would flush the change to the books."""
    leg_a = _Leg(1, FREIGHT, debit=Decimal('1000.00'))
    leg_b = _Leg(1, FREIGHT, debit=Decimal('1500.00'))
    merge_same_account_lines([leg_a, leg_b])
    assert leg_a.debit_amount == Decimal('1000.00')
    assert leg_b.debit_amount == Decimal('1500.00')


def test_a_leg_carrying_both_sides_is_left_alone():
    rows = merge_same_account_lines([
        _Leg(1, FREIGHT, debit=Decimal('100.00'), credit=Decimal('40.00')),
    ])
    assert len(rows) == 1
    assert (rows[0].debit_amount, rows[0].credit_amount) == (Decimal('100.00'),
                                                             Decimal('40.00'))


def test_no_legs_is_no_rows():
    assert merge_same_account_lines([]) == []


class TestTheDictRows:
    """The detail and preview pages build dict rows, not ORM lines. Both shapes
    must sum the same way, or one voucher reads differently depending on whether
    you open the detail page or print it -- which is the complaint that produced
    this second function."""

    def _rows(self, *triples):
        return [{'code': c, 'name': n, 'debit': Decimal(str(d)),
                 'credit': Decimal(str(cr))} for c, n, d, cr in triples]

    def test_two_debits_on_one_account_become_one_row(self):
        rows = merge_same_account_rows(self._rows(
            ('60110', 'Repairs and Maintenance', '1000.00', '0'),
            ('60110', 'Repairs and Maintenance', '1500.00', '0'),
        ))
        assert len(rows) == 1
        assert rows[0]['debit'] == Decimal('2500.00')
        assert rows[0]['name'] == 'Repairs and Maintenance'

    def test_a_different_account_is_not_swept_in(self):
        rows = merge_same_account_rows(self._rows(
            ('60110', 'Maintenance', '1000.00', '0'),
            ('60120', 'Supplies', '800.00', '0'),
        ))
        assert [r['code'] for r in rows] == ['60110', '60120']

    def test_the_same_account_on_both_sides_keeps_both_rows(self):
        rows = merge_same_account_rows(self._rows(
            ('20101', 'AP Trade', '500.00', '0'),
            ('20101', 'AP Trade', '0', '3800.00'),
        ))
        assert len(rows) == 2

    def test_rows_without_an_account_are_never_merged_together(self):
        """Two unrelated rows can both lack an account; merging them would
        invent a relationship that is not there."""
        rows = merge_same_account_rows(self._rows(
            ('—', '—', '10.00', '0'),
            ('—', '—', '20.00', '0'),
        ))
        assert len(rows) == 2

    def test_the_totals_are_unchanged(self):
        src = self._rows(('60110', 'Maintenance', '1000.00', '0'),
                         ('60110', 'Maintenance', '1500.00', '0'),
                         ('20101', 'AP Trade', '0', '2500.00'))
        rows = merge_same_account_rows(src)
        assert sum(Decimal(str(r['debit'])) for r in rows) == Decimal('2500.00')
        assert sum(Decimal(str(r['credit'])) for r in rows) == Decimal('2500.00')

    def test_the_source_rows_are_not_mutated(self):
        src = self._rows(('60110', 'Maintenance', '1000.00', '0'),
                         ('60110', 'Maintenance', '1500.00', '0'))
        merge_same_account_rows(src)
        assert src[0]['debit'] == Decimal('1000.00')
        assert src[1]['debit'] == Decimal('1500.00')
