"""Half-filled transaction-line guard (shared by the four document parsers).

A transaction line is valid in exactly two modes:

  * itemized   — both quantity AND unit_price present (amount = qty x price), or
  * amount-only — both quantity AND unit_price absent (user types the amount).

If EXACTLY ONE of quantity / unit_price is present, the line is half-filled: the
model's ``calculate_amounts()`` keeps the typed ``amount`` untouched (it only
derives when BOTH are set and > 0), so the figure that posts is almost certainly
not what the user intended. Rather than silently absorb it, reject the line.

Single source of truth: every one of SI / APV / CDV / CRV line parsers calls
``validate_line_mode`` so the rule can never drift between documents.
"""


def validate_line_mode(product_id, quantity, unit_price, amount, line_number=None):
    """Raise ``ValueError`` on a half-filled line; return ``None`` when valid.

    A line is half-filled when exactly one of ``quantity`` / ``unit_price`` is
    provided. ``product_id`` and ``amount`` are accepted for a stable call
    signature and future rules; they do not affect the current check.
    """
    has_qty = quantity is not None
    has_price = unit_price is not None
    if has_qty != has_price:
        prefix = f'Line {line_number}: ' if line_number is not None else ''
        raise ValueError(
            f'{prefix}enter a unit price with the quantity, or clear both '
            f'and type the amount.'
        )
    return None
