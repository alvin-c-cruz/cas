"""Unit tests for the manufacturing COA re-typing maps.

Validates that TYPE_BY_CODE and CLASS_BY_CODE are internally consistent
against the ACCOUNT_TYPES taxonomy — does NOT touch the live DB.
"""
import pytest
from app.accounts.account_types import ACCOUNT_TYPES, TYPES_NEEDING_CLASSIFICATION

pytestmark = [pytest.mark.unit]


def test_retype_map_is_valid():
    from scripts.retype_manufacturing_coa import TYPE_BY_CODE, CLASS_BY_CODE

    for code, t in TYPE_BY_CODE.items():
        assert t in ACCOUNT_TYPES, f"Code {code} has invalid type '{t}'"
        if t in TYPES_NEEDING_CLASSIFICATION:
            assert CLASS_BY_CODE.get(code) in ('Current', 'Non-Current'), (
                f"Code {code} (type={t}) must have a classification"
            )
        else:
            assert code not in CLASS_BY_CODE, (
                f"Code {code} (type={t}) must NOT have a classification"
            )

    # required posting codes keep their base meaning
    assert TYPE_BY_CODE['10201'] == 'Asset' and TYPE_BY_CODE['20101'] == 'Liability'
    assert TYPE_BY_CODE['30201'] == 'Equity' and TYPE_BY_CODE['30301'] == 'Equity'


def test_class_by_code_subset_of_type_by_code():
    """Every code in CLASS_BY_CODE must also be in TYPE_BY_CODE."""
    from scripts.retype_manufacturing_coa import TYPE_BY_CODE, CLASS_BY_CODE

    for code in CLASS_BY_CODE:
        assert code in TYPE_BY_CODE, (
            f"CLASS_BY_CODE has code {code} not found in TYPE_BY_CODE"
        )


def test_all_146_surviving_codes_are_covered():
    """All 146 surviving account codes (after removing 10 wrappers) are in TYPE_BY_CODE."""
    from scripts.retype_manufacturing_coa import TYPE_BY_CODE, WRAPPER_CODES

    # The 10 wrapper codes that will be deleted — they must NOT be in TYPE_BY_CODE
    for code in WRAPPER_CODES:
        assert code not in TYPE_BY_CODE, (
            f"Wrapper code {code} should not be in TYPE_BY_CODE"
        )

    # Must have exactly 146 entries
    assert len(TYPE_BY_CODE) == 146, (
        f"Expected 146 surviving codes, got {len(TYPE_BY_CODE)}"
    )
