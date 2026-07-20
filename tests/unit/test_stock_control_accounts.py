import pytest
from app.posting.control_accounts import (
    CONTROL_ACCOUNTS, DEFAULT_CONTROL_ACCOUNT_CODES,
    get_control_account, ControlAccountError,
)

STOCK_KEYS = ('inventory', 'inventory_adjustment', 'inventory_opening_equity')

def test_stock_control_keys_registered():
    for key in STOCK_KEYS:
        assert key in CONTROL_ACCOUNTS
        setting_key, label = CONTROL_ACCOUNTS[key]
        assert setting_key.endswith('_account_code')
        assert label  # human label present for the settings page

def test_stock_control_keys_not_auto_seeded():
    # Fully accountant-assigned: no legacy default code, so no seed/migration guesses one.
    for key in STOCK_KEYS:
        assert key not in DEFAULT_CONTROL_ACCOUNT_CODES

def test_unassigned_stock_control_account_raises(db_session):
    with pytest.raises(ControlAccountError):
        get_control_account('inventory')
