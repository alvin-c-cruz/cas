"""Legacy account_id -> CAS account id resolution.

`scripts/ric_coa/reconcile.py` recoded eleven legacy account codes onto CAS's
magic posting codes. A plain join on account_number therefore drops AR, AP,
Output/Input VAT, CWT, WHT-payable and Retained Earnings -- the most important
accounts in the book -- so the map must apply the recode overlay and fail closed
on anything it cannot resolve.
"""
import pytest

from scripts.legacy_import.account_map import (
    LegacyAccountError,
    ACCOUNT_RECODES,
    resolve_account_map,
)

pytestmark = [pytest.mark.unit, pytest.mark.legacy_import]


def test_recode_overlay_covers_all_eleven_reconciled_codes():
    assert ACCOUNT_RECODES == {
        '11201': '10201',    # Accounts Receivable - Trade
        '12501': '10212',    # Creditable Withholding Tax
        '12601': '10501',    # Input Tax - Capital Goods
        '12602': '10502',    # Input Tax - Domestic
        '12603': '10503',    # Input Tax - Services
        '12604': '10504',    # Input Tax - Importation
        '21101': '20101',    # Accounts Payable - Trade
        '22103-1': '20201',  # Output Tax
        '22105': '20301',    # Withholding Tax Payable - Suppliers
        '32101': '30201',    # Retained Earnings - Unappropriated
        '33101': '30301',    # Income & Expenses Summary
    }


def test_identity_join_resolves_an_unrecoded_account():
    mapping = resolve_account_map(
        used_ids={7},
        legacy_id_to_code={7: '61101'},
        live_code_to_id={'61101': 900},
        recodes=ACCOUNT_RECODES,
    )
    assert mapping == {7: 900}


def test_recoded_account_resolves_to_the_magic_code():
    """Legacy 11201 (AR-Trade) lives at 10201 in the reconciled chart."""
    mapping = resolve_account_map(
        used_ids={3},
        legacy_id_to_code={3: '11201'},
        live_code_to_id={'10201': 42},   # note: '11201' is absent from the live chart
        recodes=ACCOUNT_RECODES,
    )
    assert mapping == {3: 42}


def test_unresolved_account_fails_closed():
    with pytest.raises(LegacyAccountError) as exc:
        resolve_account_map(
            used_ids={3, 9},
            legacy_id_to_code={3: '11201', 9: '99999'},
            live_code_to_id={'10201': 42},
            recodes=ACCOUNT_RECODES,
        )
    assert '99999' in str(exc.value)


def test_unknown_legacy_account_id_fails_closed():
    with pytest.raises(LegacyAccountError):
        resolve_account_map(
            used_ids={404},
            legacy_id_to_code={},
            live_code_to_id={},
            recodes=ACCOUNT_RECODES,
        )


def test_codes_are_compared_stripped():
    mapping = resolve_account_map(
        used_ids={1},
        legacy_id_to_code={1: ' 61101 '},
        live_code_to_id={'61101': 5},
        recodes=ACCOUNT_RECODES,
    )
    assert mapping == {1: 5}
