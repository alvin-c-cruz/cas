"""Turn legacy per-book document numbers into globally unique CAS entry numbers.

`JournalEntry.entry_number` carries a GLOBAL unique index, but the legacy books
number documents per book, and those sequences overlap. Two real collisions exist
in RIC's data:

  * `receipts_x` and `petty_cash` share all 464 of their numbers. They are
    unrelated documents on independent sequences (6963 is both a 2023-01-04
    receipt and a 2024-09-27 petty-cash voucher). The book PREFIX separates them.
  * `general` has four genuinely duplicated numbers. In the raw data they look
    distinct only because five rows carry a leading TAB. Once stripped, 2,062
    rows yield 2,058 distinct numbers. These are data-quality defects in the
    client's own book, so they are suffixed deterministically and REPORTED.
"""


class LegacyNumberError(RuntimeError):
    """Raised when legacy numbers cannot be made globally unique."""


def normalize_number(raw):
    """Strip surrounding whitespace (notably the leading tab on `general_number`)."""
    return str(raw).strip()


def allocate_entry_numbers(rows):
    """Map each legacy document to its CAS `entry_number`.

    `rows` is an iterable of `(book_prefix, legacy_id, raw_number)`.
    Returns `{(book_prefix, legacy_id): entry_number}`.

    Duplicates within a book are resolved by keeping the bare number for the
    LOWEST legacy id and suffixing later ones `-2`, `-3`, ... Allocation is
    therefore deterministic and independent of input order, so a re-run produces
    byte-identical numbers.
    """
    rows = list(rows)

    groups = {}
    for prefix, legacy_id, raw in rows:
        number = normalize_number(raw)
        if not number:
            raise LegacyNumberError(
                f'blank document number for {prefix} legacy id {legacy_id}'
            )
        groups.setdefault((prefix, number), []).append(legacy_id)

    allocated = {}
    for (prefix, number), ids in groups.items():
        for ordinal, legacy_id in enumerate(sorted(ids), start=1):
            suffix = '' if ordinal == 1 else f'-{ordinal}'
            allocated[(prefix, legacy_id)] = f'{prefix}-{number}{suffix}'

    _assert_globally_unique(allocated)
    return allocated


def duplicate_groups(rows):
    """`{(prefix, number): [legacy_id, ...]}` for every number used more than once.

    Surfaced in the import report -- these are defects in the client's book.
    """
    groups = {}
    for prefix, legacy_id, raw in rows:
        groups.setdefault((prefix, normalize_number(raw)), []).append(legacy_id)
    return {key: sorted(ids) for key, ids in groups.items() if len(ids) > 1}


def _assert_globally_unique(allocated):
    seen = {}
    collisions = []
    for key, number in allocated.items():
        if number in seen:
            collisions.append((number, seen[number], key))
        seen[number] = key
    if collisions:
        detail = '; '.join(f'{n!r} claimed by {a} and {b}' for n, a, b in collisions)
        raise LegacyNumberError(f'entry_number collision after suffixing: {detail}')
