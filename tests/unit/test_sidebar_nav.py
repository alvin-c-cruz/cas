import pytest
from app.users.module_access import MODULE_REGISTRY, AREA_ORDER, GROUP_ORDER

pytestmark = [pytest.mark.unit]


def test_every_registry_entry_has_valid_area_and_group():
    for m in MODULE_REGISTRY:
        assert m.get('area') in AREA_ORDER, f"{m['key']} has invalid/missing area {m.get('area')!r}"
        assert m.get('group') in GROUP_ORDER, f"{m['key']} has invalid/missing group {m.get('group')!r}"


def test_section_field_preserved():
    # section must remain (permission grid + TRANSACTION_KEYS depend on it)
    keys = {m['key']: m for m in MODULE_REGISTRY}
    assert keys['accounts_receivable']['section'] == 'Transactions'
    assert keys['income_statement']['section'] == 'Financial Reports'


def test_known_area_assignments():
    keys = {m['key']: m for m in MODULE_REGISTRY}
    assert (keys['customers']['area'], keys['customers']['group']) == ('Sales', 'Masters')
    assert (keys['accounts_payable']['area'], keys['accounts_payable']['group']) == ('Purchases', 'Documents')
    assert (keys['income_statement']['area'], keys['income_statement']['group']) == ('Accounting', 'Financial Statements')
    assert (keys['books_of_accounts']['area'], keys['books_of_accounts']['group']) == ('Compliance', 'BIR')
