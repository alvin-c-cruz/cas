import pytest
from app.users.module_access import MODULE_REGISTRY, AREA_ORDER, GROUP_ORDER, build_sidebar
from app.users.models import User

pytestmark = [pytest.mark.unit, pytest.mark.sidebar_nav]


def _user(role, perms=None):
    u = User(username=f'{role}_nav', email=f'{role}_nav@t.com', full_name='Nav', role=role, is_active=True)
    u.set_password('x')
    if perms is not None:
        u.set_book_permissions(perms)
    return u


def test_admin_sees_all_areas_ordered(db_session):
    tree = build_sidebar(_user('admin'))
    areas = [a['area'] for a in tree]
    # admin can access every ENABLED module; Payroll has no modules so it is omitted.
    # Inventory is also omitted because products + units_of_measure are optional and
    # default_enabled=False — admin still cannot see an optional area that is turned off.
    assert areas == ['Sales', 'Purchases', 'Accounting', 'Compliance']
    sales = next(a for a in tree if a['area'] == 'Sales')
    assert [g['group'] for g in sales['groups']] == ['Documents', 'Masters', 'Reports']
    docs = next(g for g in sales['groups'] if g['group'] == 'Documents')['modules']
    # sales_orders is CORE (non-optional per P-58) so always visible for admin
    assert [m['key'] for m in docs] == ['sales_orders', 'accounts_receivable', 'collections']


def test_enabling_inventory_modules_shows_inventory_area(db_session):
    """When the optional products + UOM modules are turned on, admin sees an Inventory area."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache

    # Enable both optional Inventory modules (AppSettings.set_setting commits internally)
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    AppSettings.set_setting('module_enabled:products', '1')
    clear_module_config_cache()
    try:
        tree = build_sidebar(_user('admin'))
        areas = [a['area'] for a in tree]
        assert 'Inventory' in areas, f"Expected Inventory area after enabling modules; got {areas}"

        inv = next(a for a in tree if a['area'] == 'Inventory')
        all_module_keys = [m['key'] for g in inv['groups'] for m in g['modules']]
        assert set(all_module_keys) == {'products', 'units_of_measure'}
    finally:
        clear_module_config_cache()


def test_empty_areas_and_groups_omitted(db_session):
    # accountant granted only general_ledger → only Accounting/Ledger present
    tree = build_sidebar(_user('accountant', {'general_ledger': True}))
    assert [a['area'] for a in tree] == ['Accounting']
    acct = tree[0]
    assert [g['group'] for g in acct['groups']] == ['Ledger']
    assert [m['key'] for m in acct['groups'][0]['modules']] == ['general_ledger']


def test_cas_only_shows_one_accounting_area(db_session):
    # accountant granted the accounting set → one Accounting area with its sub-groups
    perms = {k: True for k in ['journal_entries', 'chart_of_accounts', 'general_ledger',
                               'trial_balance', 'income_statement', 'balance_sheet',
                               'cash_flow', 'fiscal_year_close']}
    tree = build_sidebar(_user('accountant', perms))
    assert [a['area'] for a in tree] == ['Accounting']
    assert [g['group'] for g in tree[0]['groups']] == ['Journals', 'Ledger', 'Financial Statements']


def test_never_includes_inaccessible_module(db_session):
    tree = build_sidebar(_user('accountant', {'accounts_receivable': True}))
    all_keys = [m['key'] for a in tree for g in a['groups'] for m in g['modules']]
    assert all_keys == ['accounts_receivable']


def test_every_registry_entry_has_valid_area_and_group():
    """Every entry that build_sidebar can render needs a valid area/group.

    Deliberate exception (P-69 Task 6): entries with `endpoints == ()` are
    endpoint-less by design (e.g. preprinted_forms/print_layouts) — the
    before_request auto-gate never maps a route to them, and they carry
    area=None/group=None on purpose so build_sidebar never surfaces them; their
    nav (if any) is added by hand instead. See app/users/module_access.py.
    """
    for m in MODULE_REGISTRY:
        if m['endpoints'] == ():
            assert m.get('area') is None, f"{m['key']} is endpoint-less but has a non-None area"
            assert m.get('group') is None, f"{m['key']} is endpoint-less but has a non-None group"
            continue
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
