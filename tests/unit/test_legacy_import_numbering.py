"""Legacy entry-number normalization.

The source books number documents per-book, and those numbers are NOT globally
unique -- while `JournalEntry.entry_number` carries a global unique index. Two
real collisions exist in RIC's data:

  * `receipts_x` and `petty_cash` share all 464 of their numbers (unrelated
    documents on independent sequences).
  * `general` has four genuinely duplicated numbers, masked in the raw data by a
    leading tab on five rows.
"""
import pytest

from scripts.legacy_import.numbering import (
    LegacyNumberError,
    allocate_entry_numbers,
    normalize_number,
)

pytestmark = [pytest.mark.unit, pytest.mark.legacy_import]


def test_normalize_strips_the_leading_tab():
    assert normalize_number('\t202509-050') == '202509-050'
    assert normalize_number('  6963  ') == '6963'
    assert normalize_number(6963) == '6963'


def test_prefix_separates_receipts_x_from_petty_cash():
    """Both books number a document 6963; the book prefix disambiguates them."""
    allocated = allocate_entry_numbers([
        ('CRJX', 1, '6963'),
        ('PCV', 726, '6963'),
    ])
    assert allocated[('CRJX', 1)] == 'CRJX-6963'
    assert allocated[('PCV', 726)] == 'PCV-6963'


def test_duplicate_general_numbers_get_a_deterministic_suffix():
    """The later legacy id is suffixed; the earlier keeps the bare number."""
    allocated = allocate_entry_numbers([
        ('JV', 2023, '202510-033'),   # deliberately out of id order
        ('JV', 1894, '202510-033'),
    ])
    assert allocated[('JV', 1894)] == 'JV-202510-033'
    assert allocated[('JV', 2023)] == 'JV-202510-033-2'


def test_duplicates_are_suffixed_after_whitespace_is_stripped():
    """The raw values differ only by a tab, so they must collide once stripped."""
    allocated = allocate_entry_numbers([
        ('JV', 1878, '\t202509-050'),
        ('JV', 1881, '202509-050'),
    ])
    assert allocated[('JV', 1878)] == 'JV-202509-050'
    assert allocated[('JV', 1881)] == 'JV-202509-050-2'


def test_allocation_is_deterministic_across_runs():
    rows = [('JV', 2023, '202510-033'), ('JV', 1894, '202510-033')]
    assert allocate_entry_numbers(rows) == allocate_entry_numbers(list(reversed(rows)))


def test_a_residual_collision_raises_rather_than_silently_overwriting():
    """If suffixing cannot make numbers unique, fail closed."""
    with pytest.raises(LegacyNumberError, match='collision'):
        allocate_entry_numbers([
            ('JV', 1, '202510-033'),
            ('JV', 2, '202510-033'),
            ('JV', 3, '202510-033-2'),   # collides with the suffix minted for id 2
        ])


def test_blank_number_raises():
    with pytest.raises(LegacyNumberError, match='blank'):
        allocate_entry_numbers([('JV', 1, '   ')])


def test_result_is_globally_unique():
    rows = [
        ('SJ', 1, '0028061'), ('SJX', 1, '0000001'),
        ('CRJ', 1, '01143'), ('CRJX', 1, '6963'),
        ('CDJ', 1, '49036'), ('CDJX', 1, '18053'),
        ('PJ', 1, '009516'), ('PJX', 1, '002453'),
        ('JV', 1, '202509-050'), ('PCV', 1, '6963'),
    ]
    allocated = allocate_entry_numbers(rows)
    assert len(set(allocated.values())) == len(rows)
