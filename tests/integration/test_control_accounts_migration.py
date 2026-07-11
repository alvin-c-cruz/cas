# tests/integration/test_control_accounts_migration.py
# The authoritative migration check is the real-DB-copy run in Step 4
# (conftest create_all() does not exercise Alembic). This test only pins the
# backfill mapping so it cannot silently drift from the resolver.
from app.posting.control_accounts import DEFAULT_CONTROL_ACCOUNT_CODES, CONTROL_ACCOUNTS


def test_backfill_mapping_matches_resolver():
    expected = {
        'ar_trade_account_code':       '10201',
        'ap_trade_account_code':       '20101',
        'creditable_wht_account_code': '10212',
        'wht_payable_account_code':    '20301',
    }
    for key, code in DEFAULT_CONTROL_ACCOUNT_CODES.items():
        setting_key, _ = CONTROL_ACCOUNTS[key]
        assert expected[setting_key] == code
