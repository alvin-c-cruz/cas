"""Unit tests for app/common/amount_to_words.py — the legally-operative amount line
on a printed check (NIL Sec.17(b): the words control over the figures).

Format (locked here, confirmable with the bank in Phase 0):
    "<INTEGER WORDS> PESO(S) AND nn/100 ONLY"  — ALL-CAPS, no interior "and",
    always includes "AND nn/100", singular PESO iff the peso count == 1.

The property test uses an INDEPENDENT words->Decimal parser (a different code path
from the speller) so the round-trip actually proves correctness rather than being
tautological.
"""
import random
from decimal import Decimal

import pytest

from app.common.amount_to_words import amount_to_words

pytestmark = [pytest.mark.unit]


# --- independent oracle: parse the words back to a Decimal (NOT the speller's code) ---
_ONES = {w: i for i, w in enumerate(
    'ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN '
    'FOURTEEN FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN'.split())}
_TENS = {'TWENTY': 20, 'THIRTY': 30, 'FORTY': 40, 'FIFTY': 50,
         'SIXTY': 60, 'SEVENTY': 70, 'EIGHTY': 80, 'NINETY': 90}
_SCALES = {'THOUSAND': 10**3, 'MILLION': 10**6, 'BILLION': 10**9, 'TRILLION': 10**12}


def _parse_int_words(s):
    total, current = 0, 0
    for tok in s.replace('-', ' ').split():
        if tok in _ONES:
            current += _ONES[tok]
        elif tok in _TENS:
            current += _TENS[tok]
        elif tok == 'HUNDRED':
            current *= 100
        elif tok in _SCALES:
            total += current * _SCALES[tok]
            current = 0
        else:
            raise AssertionError(f'unparseable word: {tok!r}')
    return total + current


def parse_words(s):
    """Inverse of amount_to_words — deliberately independent implementation."""
    assert s == s.upper(), 'must be ALL-CAPS'
    assert s.endswith(' ONLY'), 'must end with ONLY'
    s = s[:-len(' ONLY')]
    peso_words, cents_part = s.rsplit(' AND ', 1)
    assert cents_part.endswith('/100')
    cents = int(cents_part[:-len('/100')])
    assert 0 <= cents <= 99
    peso_words = peso_words.rsplit(' PESO', 1)[0]   # strip ' PESOS' or ' PESO'
    return Decimal(_parse_int_words(peso_words)) + (Decimal(cents) / 100)


class TestGuards:
    def test_zero_raises(self):
        with pytest.raises(ValueError):
            amount_to_words(Decimal('0.00'))

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            amount_to_words(Decimal('-5.00'))

    def test_non_decimal_raises(self):
        for bad in (1.0, '1.00', 100, None):
            with pytest.raises(TypeError):
                amount_to_words(bad)

    def test_more_than_two_decimals_raises(self):
        with pytest.raises(ValueError):
            amount_to_words(Decimal('1.005'))

    def test_above_supported_range_raises(self):
        with pytest.raises(ValueError):
            amount_to_words(Decimal('1000000000000000'))   # 1e15, beyond trillions


class TestBoundaryTable:
    CASES = {
        '0.01': 'ZERO PESOS AND 01/100 ONLY',
        '0.05': 'ZERO PESOS AND 05/100 ONLY',
        '0.99': 'ZERO PESOS AND 99/100 ONLY',
        '1.00': 'ONE PESO AND 00/100 ONLY',
        '1.05': 'ONE PESO AND 05/100 ONLY',
        '2.00': 'TWO PESOS AND 00/100 ONLY',
        '11.00': 'ELEVEN PESOS AND 00/100 ONLY',
        '20.00': 'TWENTY PESOS AND 00/100 ONLY',
        '21.00': 'TWENTY-ONE PESOS AND 00/100 ONLY',
        '45.00': 'FORTY-FIVE PESOS AND 00/100 ONLY',
        '100.00': 'ONE HUNDRED PESOS AND 00/100 ONLY',
        '105.00': 'ONE HUNDRED FIVE PESOS AND 00/100 ONLY',
        '123.45': 'ONE HUNDRED TWENTY-THREE PESOS AND 45/100 ONLY',
        '1000.00': 'ONE THOUSAND PESOS AND 00/100 ONLY',
        '1001.00': 'ONE THOUSAND ONE PESOS AND 00/100 ONLY',
        '1234.56': 'ONE THOUSAND TWO HUNDRED THIRTY-FOUR PESOS AND 56/100 ONLY',
        '1000000.00': 'ONE MILLION PESOS AND 00/100 ONLY',
        '1000000000.00': 'ONE BILLION PESOS AND 00/100 ONLY',
        '9999999999999.99':
            'NINE TRILLION NINE HUNDRED NINETY-NINE BILLION NINE HUNDRED NINETY-NINE '
            'MILLION NINE HUNDRED NINETY-NINE THOUSAND NINE HUNDRED NINETY-NINE '
            'PESOS AND 99/100 ONLY',
    }

    @pytest.mark.parametrize('amount,expected', CASES.items())
    def test_exact_wording(self, amount, expected):
        assert amount_to_words(Decimal(amount)) == expected


class TestInvariants:
    def test_decimal_not_float_centavo_split(self):
        # Decimal('1.10') must be 10/100 (float 1.10*100 == 109.9999...).
        assert amount_to_words(Decimal('1.10')).endswith('AND 10/100 ONLY')

    def test_transposition_distinct(self):
        assert amount_to_words(Decimal('10.10')) != amount_to_words(Decimal('10.01'))

    def test_always_caps_only_and_slash100(self):
        for a in ('0.01', '1.00', '1234.56', '9999999999999.99'):
            out = amount_to_words(Decimal(a))
            assert out == out.upper()
            assert out.endswith(' ONLY')
            assert '/100' in out

    def test_no_currency_symbol(self):
        out = amount_to_words(Decimal('1234.56'))
        for sym in ('₱', '$', 'PHP', '&#8369;'):
            assert sym not in out


class TestRoundTripOracle:
    def test_matrix_round_trips(self):
        for a in TestBoundaryTable.CASES:
            assert parse_words(amount_to_words(Decimal(a))) == Decimal(a)

    def test_property_round_trip_random(self):
        # Independent parser proves the speller across the whole range (non-tautological).
        rnd = random.Random(20260707)
        for _ in range(3000):
            centavos = rnd.randint(1, 9_999_999_999_999_99)   # 0.01 .. 9,999,999,999,999.99
            value = (Decimal(centavos) / 100)
            out = amount_to_words(value)
            assert parse_words(out) == value, f'round-trip failed for {value}: {out!r}'
