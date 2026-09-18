"""AC 1, 4 and 5, the dual-write, and who may delete."""
import json
import pytest
from app import db
from app.audit.models import AuditLog
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
    default_row = _mk('Default', is_default=True)
    before_payload = default_row.payload
    lay = get_layout(branch_id=SCOPE)
    col = next(c for c in lay['lineItems']['columns'] if c['key'] == 'pr_number')
    col['x'] = 77
    save_layout(lay, 'admin', branch_id=SCOPE)

    legacy = json.loads(AppSettings.get_setting(f'po_preprinted_layout:{SCOPE}'))
    legacy_col = next(c for c in legacy['lineItems']['columns'] if c['key'] == 'pr_number')
    assert legacy_col['x'] == 77

    # THE PRIMARY new behaviour under test: the named_print_layouts row itself
    # must have been written, not just the transitional legacy key. Reload from
    # the DB rather than trusting the in-memory object, and assert the payload
    # actually CONTAINS the saved value -- not merely that it changed, which
    # would also pass if the row had been overwritten with garbage.
    reloaded = db.session.get(PrintLayout, default_row.id)
    assert reloaded.payload != before_payload
    reloaded_col = next(c for c in json.loads(reloaded.payload)['lineItems']['columns']
                        if c['key'] == 'pr_number')
    assert reloaded_col['x'] == 77


def test_saving_a_NON_default_layout_leaves_the_legacy_key_alone(db_session):
    from app.purchase_orders.preprinted_layout import get_layout, save_layout
    _mk('Default', is_default=True)
    other = _mk('Other')
    before_payload = other.payload
    AppSettings.set_setting(f'po_preprinted_layout:{SCOPE}', json.dumps({'marker': 'untouched'}),
                            'system')
    lay = get_layout(branch_id=SCOPE)
    col = next(c for c in lay['lineItems']['columns'] if c['key'] == 'pr_number')
    col['x'] = 88
    save_layout(lay, 'admin', branch_id=SCOPE, layout_id=other.id)

    assert json.loads(AppSettings.get_setting(f'po_preprinted_layout:{SCOPE}'))['marker'] \
        == 'untouched'

    # The explicitly-targeted, non-default row must still have been written --
    # the dual-write being skipped must not mean the save itself was skipped.
    reloaded = db.session.get(PrintLayout, other.id)
    assert reloaded.payload != before_payload
    reloaded_col = next(c for c in json.loads(reloaded.payload)['lineItems']['columns']
                        if c['key'] == 'pr_number')
    assert reloaded_col['x'] == 88


def test_saving_with_layout_id_none_targets_the_default_and_never_raises(db_session):
    """layout_id=None must keep meaning 'the scope's default' for every one of the
    eleven pre-existing pre-printed modules that never pass layout_id -- and must
    never raise, even when (as here) no named_print_layouts row exists yet for
    this scope. Regression guard for the FINDING 2 fix below."""
    from app.purchase_orders.preprinted_layout import get_layout, save_layout
    lay = get_layout(branch_id=SCOPE)
    clean = save_layout(lay, 'admin', branch_id=SCOPE)  # no layout_id -- must not raise
    assert clean is not None
    assert AppSettings.get_setting(f'po_preprinted_layout:{SCOPE}') is not None


def test_saving_with_an_unknown_layout_id_is_refused_and_leaves_no_trace(db_session):
    """FINDING 2: an explicit layout_id that names no row (deleted by someone else
    between page load and submit) must be refused BEFORE anything is written --
    not silently dropped. `log_audit` runs unconditionally on every path that
    reaches it, so a silently-dropped save would still write an audit row
    asserting the save happened: a lying audit entry, not a harmless no-op. The
    audit-row assertion is the one that matters here."""
    from app.purchase_orders.preprinted_layout import get_layout, save_layout
    _mk('Default', is_default=True)
    AppSettings.set_setting(f'po_preprinted_layout:{SCOPE}', json.dumps({'marker': 'untouched'}),
                            'system')
    audit_count_before = AuditLog.query.count()
    lay = get_layout(branch_id=SCOPE)

    with pytest.raises(ValueError):
        save_layout(lay, 'admin', branch_id=SCOPE, layout_id=999999)

    assert json.loads(AppSettings.get_setting(f'po_preprinted_layout:{SCOPE}'))['marker'] \
        == 'untouched'
    assert AuditLog.query.count() == audit_count_before


def test_renaming_an_unknown_layout_raises(db_session):
    """FINDING 3: rename_layout had no None-guard, unlike delete_layout -- an
    unknown id raised a bare AttributeError instead of a clear, consistent error."""
    with pytest.raises(ValueError):
        service.rename_layout(999999, 'New name')


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
