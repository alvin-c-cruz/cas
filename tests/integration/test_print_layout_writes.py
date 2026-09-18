"""AC 1, 4 and 5, the dual-write, and who may delete."""
import json
import pytest
from app import db
from app.settings import AppSettings
from app.print_layouts.models import PrintLayout, PrintLayoutDevicePref
from app.print_layouts import service
from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

DOC, SCOPE = 'purchase_orders', 1


def _mk(name, is_default=False, marker='x'):
    r = PrintLayout(doc_type=DOC, scope_id=SCOPE, name=name, is_default=is_default,
                    payload=json.dumps({'marker': marker}))
    db.session.add(r); db.session.commit()
    return r


def test_two_named_layouts_coexist(db_session):
    """AC 1: neither purchaser overwrites the other."""
    service.create_layout(DOC, SCOPE, 'Angilyn - LX-310', json.dumps({'marker': 'a'}), None)
    service.create_layout(DOC, SCOPE, 'Purchasing - HP', json.dumps({'marker': 'b'}), None)
    names = [r.name for r in service.list_layouts(DOC, SCOPE)]
    assert names == ['Angilyn - LX-310', 'Purchasing - HP']


def test_renaming_does_not_move_any_selection(db_session):
    """AC 5: the pref holds layout_id, so a rename cannot repoint a workstation."""
    row = _mk('Old name')
    service.set_device_layout('dev1', DOC, SCOPE, row.id)
    service.rename_layout(row.id, 'New name')
    pref = PrintLayoutDevicePref.query.filter_by(device_id='dev1').one()
    assert pref.layout_id == row.id
    assert pref.layout.name == 'New name'


def test_deleting_a_selected_layout_leaves_printing_working(db_session):
    """AC 4: the workstation falls back to the default, and the pref row survives."""
    default = _mk('Default', is_default=True, marker='default')
    other = _mk('Other', marker='other')
    service.set_device_layout('dev1', DOC, SCOPE, other.id)
    service.delete_layout(other.id)
    pref = PrintLayoutDevicePref.query.filter_by(device_id='dev1').one()
    assert pref.layout_id is None
    resolved = service.resolve_layout(DOC, SCOPE, 'dev1')
    assert resolved.id == default.id


def test_the_default_layout_cannot_be_deleted(db_session):
    default = _mk('Default', is_default=True)
    with pytest.raises(ValueError):
        service.delete_layout(default.id)


def test_saving_the_default_also_writes_the_legacy_key(db_session):
    """Transitional dual-write: a rollback must keep alignment work done since the
    migration, not just the state at migration time.

    NOTE: mutates the 'pr_number' LINE-ITEM COLUMN, not a top-level field -- PO's
    FIELD_KEYS has no 'pr_number' entry (that is a COLUMN_KEYS entry: the PR # printed
    per line), so `lay['fields']['pr_number']` would KeyError. Verified against
    app/purchase_orders/preprinted_layout.py.
    """
    from app.purchase_orders.preprinted_layout import get_layout, save_layout
    _mk('Default', is_default=True)
    lay = get_layout(branch_id=SCOPE)
    col = next(c for c in lay['lineItems']['columns'] if c['key'] == 'pr_number')
    col['x'] = 77
    save_layout(lay, 'admin', branch_id=SCOPE)
    legacy = json.loads(AppSettings.get_setting(f'po_preprinted_layout:{SCOPE}'))
    legacy_col = next(c for c in legacy['lineItems']['columns'] if c['key'] == 'pr_number')
    assert legacy_col['x'] == 77


def test_saving_a_NON_default_layout_leaves_the_legacy_key_alone(db_session):
    from app.purchase_orders.preprinted_layout import get_layout, save_layout
    _mk('Default', is_default=True)
    other = _mk('Other')
    AppSettings.set_setting(f'po_preprinted_layout:{SCOPE}', json.dumps({'marker': 'untouched'}),
                            'system')
    lay = get_layout(branch_id=SCOPE)
    save_layout(lay, 'admin', branch_id=SCOPE, layout_id=other.id)
    assert json.loads(AppSettings.get_setting(f'po_preprinted_layout:{SCOPE}'))['marker'] \
        == 'untouched'


@pytest.mark.parametrize('role,allowed', [
    ('admin', True), ('chief_accountant', True), ('accountant', False), ('staff', False),
    ('viewer', False), ('', False),
])
def test_who_may_delete_a_layout(role, allowed):
    """Narrower than can_edit_print_layout: delete is the one action with
    cross-machine blast radius. A blank/unknown role must fail closed."""
    assert User(role=role).can_delete_print_layout is allowed


@pytest.mark.parametrize('role,allowed', [
    ('admin', True), ('chief_accountant', True), ('accountant', True), ('staff', True),
    ('viewer', False),
])
def test_edit_access_is_unchanged(role, allowed):
    """This feature must not take away what staff can already do."""
    assert User(role=role).can_edit_print_layout is allowed
