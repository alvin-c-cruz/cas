"""Spell a peso amount for the legally-operative words line on a printed check.

A printed check is a negotiable instrument and, under the Negotiable Instruments Law
(Act 2031) Sec. 17(b), where the sum in words and the sum in figures differ, the
**words control**. So this helper — not the figure formatter — is the legally binding
amount. It is deliberately tiny, dependency-free, and exhaustively tested
(`tests/unit/test_amount_to_words.py`, incl. an independent spell->parse round-trip).

Output format: ``"<INTEGER WORDS> PESO(S) AND nn/100 ONLY"`` — ALL-CAPS, no interior
"and" (only the "AND" before the centavos), singular "PESO" iff the peso count is 1,
centavos always zero-padded to two digits. No currency symbol (per the house rule).

Contract:
    amount_to_words(value: Decimal) -> str
    - `value` MUST be a Decimal (a float would carry rounding error into money) — else TypeError.
    - value <= 0, more than 2 decimal places, or >= 1e15 (beyond trillions) -> ValueError:
      a check is never written for zero/negative, money is always 2dp, and the
      supported range covers the Numeric(15,2) column (max 9,999,999,999,999.99).
"""
from decimal import Decimal

_ONES = ('ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE '
         'THIRTEEN FOURTEEN FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN').split()
_TENS = ('', '', 'TWENTY', 'THIRTY', 'FORTY', 'FIFTY',
         'SIXTY', 'SEVENTY', 'EIGHTY', 'NINETY')
# Scale words for each group of three digits, least-significant first.
_SCALES = ('', 'THOUSAND', 'MILLION', 'BILLION', 'TRILLION')
_MAX = Decimal(10) ** 15   # 999,999,999,999,999.99 is the top of the supported range


def _three(n):
    """Words for 0..999 (no leading/trailing spaces)."""
    parts = []
    if n >= 100:
        parts.append(_ONES[n // 100])
        parts.append('HUNDRED')
        n %= 100
    if n >= 20:
        t = _TENS[n // 10]
        parts.append(f'{t}-{_ONES[n % 10]}' if n % 10 else t)
    elif n > 0:
        parts.append(_ONES[n])
    return ' '.join(parts)


def _int_to_words(n):
    """Words for a non-negative integer (0 -> 'ZERO')."""
    if n == 0:
        return 'ZERO'
    groups = []
    scale = 0
    while n > 0:
        n, rem = divmod(n, 1000)
        if rem:
            words = _three(rem)
            groups.append(f'{words} {_SCALES[scale]}'.strip())
        scale += 1
    return ' '.join(reversed(groups))


def amount_to_words(value):
    if not isinstance(value, Decimal):
        raise TypeError('amount_to_words requires a Decimal (never a float)')
    if value <= 0:
        raise ValueError('cannot spell a zero or negative check amount')
    if value != value.quantize(Decimal('0.01')):
        raise ValueError('amount must have at most two decimal places')
    if value >= _MAX:
        raise ValueError('amount is beyond the supported range')

    centavos_total = int((value * 100).to_integral_value())   # exact: value is 2dp
    pesos, centavos = divmod(centavos_total, 100)
    peso_word = 'PESO' if pesos == 1 else 'PESOS'
    return f'{_int_to_words(pesos)} {peso_word} AND {centavos:02d}/100 ONLY'
