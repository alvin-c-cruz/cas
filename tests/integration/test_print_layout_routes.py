"""The four routes, and AC 2 + AC 3: the SELECTION belongs to the workstation, so it
survives logout and applies to whoever sits down next."""
import json
import pytest
from app import db
from app.audit.models import AuditLog
from app.print_layouts.models import PrintLayout, PrintLayoutDevicePref
from app.print_layouts.device import DEVICE_COOKIE
from app.print_layouts.service import resolve_layout
from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

SCOPE = 1


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders is an optional module (default_enabled=False) -- without this,
    enforce_module_access 404s every route in this blueprint for every role, admin
    included. Mirrors tests/integration/test_po_amend.py's identically-named fixture."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id
    # Flask-Login caches the loaded user on flask.g for the life of the app
    # context. The session-scoped `app` fixture keeps ONE app context open for
    # the whole test session and the test client reuses it per request rather
    # than pushing a fresh one, so g._login_user (and therefore current_user)
    # would otherwise stay stale across a mid-test user switch. Mirrors
    # tests/integration/_so_helpers.py::_login.
    import flask
    flask.g.pop('_login_user', None)


def _user(db_session, branch, username, role):
    u = User(username=username, email=username + '@test.com', full_name=username,
             role=role, is_active=True)
    u.set_password('testpass123')
    db_session.add(u); db_session.flush(); u.set_branches([branch])
    # purchase_orders is per_user-gated (module_access.py) on top of the instance
    # gate the po_enabled fixture flips above; a bare non-admin role otherwise
    # never reaches the route at all (redirected before the view runs), which
    # would make every permission assertion below pass for the wrong reason.
    from app.users.module_access import default_all_permissions
    u.set_book_permissions(default_all_permissions())
    db_session.commit()
    return u


def _mk(name, is_default=False, marker='x'):
    r = PrintLayout(doc_type='purchase_orders', scope_id=SCOPE, name=name,
                    is_default=is_default, payload=json.dumps({'marker': marker}))
    db.session.add(r); db.session.commit()
    return r


def test_save_as_creates_a_named_layout(client, db_session, main_branch):
    _mk('Default', is_default=True)
    _login(client, _user(db_session, main_branch, 'acct1', 'accountant'), main_branch)
    resp = client.post('/purchase-orders/print-layout/save-as',
                       json={'name': 'Purchasing - HP', 'branch_id': SCOPE})
    assert resp.status_code == 200 and resp.get_json()['ok'] is True
    assert PrintLayout.query.filter_by(name='Purchasing - HP').one()


def test_delete_is_refused_for_staff_and_allowed_for_admin(client, db_session, main_branch):
    _mk('Default', is_default=True)
    doomed = _mk('Doomed')
    _login(client, _user(db_session, main_branch, 'staff1', 'staff'), main_branch)
    assert client.post('/purchase-orders/print-layout/delete',
                       json={'layout_id': doomed.id}).status_code == 403
    _login(client, _user(db_session, main_branch, 'admin1', 'admin'), main_branch)
    assert client.post('/purchase-orders/print-layout/delete',
                       json={'layout_id': doomed.id}).status_code == 200


def test_the_selection_survives_logout(client, db_session, main_branch):
    """AC 3."""
    _mk('Default', is_default=True)
    other = _mk('Other', marker='other')
    user = _user(db_session, main_branch, 'p1', 'staff')
    client.set_cookie(DEVICE_COOKIE, 'workstation-A')
    _login(client, user, main_branch)
    client.post('/purchase-orders/print-layout/select',
                json={'layout_id': other.id, 'branch_id': SCOPE})
    client.get('/logout')
    _login(client, user, main_branch)
    pref = PrintLayoutDevicePref.query.filter_by(device_id='workstation-A').one()
    assert pref.layout_id == other.id


def test_the_selection_belongs_to_the_desk_not_the_person(client, db_session, main_branch):
    """AC 2, as redefined by the per-workstation decision: a DIFFERENT user at the same
    workstation inherits its layout, and the same user at a different workstation does
    not carry it with them."""
    _mk('Default', is_default=True)
    other = _mk('Other', marker='other')
    angilyn = _user(db_session, main_branch, 'angilyn', 'staff')
    newhire = _user(db_session, main_branch, 'newhire', 'staff')

    client.set_cookie(DEVICE_COOKIE, 'workstation-A')
    _login(client, angilyn, main_branch)
    client.post('/purchase-orders/print-layout/select',
                json={'layout_id': other.id, 'branch_id': SCOPE})

    _login(client, newhire, main_branch)          # same desk, different person
    assert resolve_layout('purchase_orders', SCOPE, 'workstation-A').id == other.id

    # same person, different desk -> the default, NOT what she picked at desk A
    assert resolve_layout('purchase_orders', SCOPE, 'workstation-B').name == 'Default'


def test_every_write_is_audited_with_a_real_diff(client, db_session, main_branch):
    _mk('Default', is_default=True)
    row = _mk('Rename me')
    _login(client, _user(db_session, main_branch, 'acct2', 'accountant'), main_branch)
    client.post('/purchase-orders/print-layout/rename',
                json={'layout_id': row.id, 'name': 'Renamed'})
    entry = (AuditLog.query.filter_by(module='purchase_orders',
                                      record_identifier='po_print_layout')
             .order_by(AuditLog.id.desc()).first())
    assert entry is not None
    assert entry.old_values and entry.old_values != '{}', 'audit logged an empty before-state'
    assert 'Rename me' in str(entry.old_values)


# --- final review IMPORTANT 2: a name collision is a friendly 400, not a 500 ------

def test_save_as_onto_an_existing_name_is_a_friendly_400(client, db_session, main_branch):
    _mk('Default', is_default=True)
    _mk('Purchasing - HP')
    _login(client, _user(db_session, main_branch, 'acct3', 'accountant'), main_branch)
    resp = client.post('/purchase-orders/print-layout/save-as',
                       json={'name': 'Purchasing - HP', 'branch_id': SCOPE})
    assert resp.status_code == 400
    assert 'already exists' in resp.get_json()['error']


def test_renaming_onto_an_existing_name_is_a_friendly_400_not_a_500(client, db_session, main_branch):
    """Before this fix: rename_layout assigned row.name and committed with no
    uniqueness pre-check, so the DB-enforced UNIQUE (doc_type, scope_id, name)
    constraint surfaced as an uncaught IntegrityError -- this app's generic
    error handlers are disabled, so that was a 500, not the same friendly 4xx
    shape every other refusal on these routes gives."""
    _mk('Default', is_default=True)
    _mk('Purchasing - HP')
    victim = _mk('Purchasing - Epson')
    _login(client, _user(db_session, main_branch, 'acct4', 'accountant'), main_branch)
    resp = client.post('/purchase-orders/print-layout/rename',
                       json={'layout_id': victim.id, 'name': 'Purchasing - HP'})
    assert resp.status_code == 400
    assert 'already exists' in resp.get_json()['error']
    # nothing persisted -- the victim's own name is untouched
    assert db.session.get(PrintLayout, victim.id).name == 'Purchasing - Epson'


# --- final review IMPORTANT 3: rename/delete must validate scope, like select ----

def test_rename_refuses_a_layout_from_a_foreign_scope(client, db_session, main_branch,
                                                       branch_manila):
    """can_edit_print_layout includes accountant and staff, who ARE
    branch-scoped -- without this check, a purchaser assigned only to
    main_branch could rename branch_manila's layout by posting its id."""
    foreign = PrintLayout(doc_type='purchase_orders', scope_id=branch_manila.id,
                          name='Manila Layout', is_default=True, payload=json.dumps({}))
    db.session.add(foreign); db.session.commit()
    _mk('Default', is_default=True)   # main_branch's own default
    _login(client, _user(db_session, main_branch, 'acct5', 'accountant'), main_branch)
    resp = client.post('/purchase-orders/print-layout/rename',
                       json={'layout_id': foreign.id, 'name': 'Hijacked'})
    assert resp.status_code == 404
    assert db.session.get(PrintLayout, foreign.id).name == 'Manila Layout'


def test_delete_refuses_a_layout_from_a_foreign_scope(client, db_session, main_branch,
                                                       branch_manila):
    """Delete is admin/chief_accountant only today (both all-branch, so this is
    hygiene rather than a live hole right now) -- but the moment a second
    document type adopts named_print_layouts, an id alone could delete another
    document's row without this."""
    foreign = PrintLayout(doc_type='purchase_orders', scope_id=branch_manila.id,
                          name='Manila Other', payload=json.dumps({}))
    db.session.add(foreign); db.session.commit()
    _mk('Default', is_default=True)   # main_branch's own default
    _login(client, _user(db_session, main_branch, 'admin2', 'admin'), main_branch)
    resp = client.post('/purchase-orders/print-layout/delete',
                       json={'layout_id': foreign.id})
    assert resp.status_code == 404
    assert db.session.get(PrintLayout, foreign.id) is not None


# --- final review IMPORTANT 4: the first layout in a fresh scope is the default ---

def test_the_first_layout_in_a_fresh_scope_becomes_the_default(client, db_session, main_branch):
    """No migrated legacy key means no default row exists yet for this scope
    (on the real philgen DB, only branch 1 has a migrated row). Before this
    fix, the first "Save as..." was non-default, resolution reached it only
    via the "first row by id" fallback, and delete_layout's "refuse to delete
    the default" guard protected nothing -- there was no default row to
    refuse deleting."""
    _login(client, _user(db_session, main_branch, 'acct6', 'accountant'), main_branch)
    resp = client.post('/purchase-orders/print-layout/save-as',
                       json={'name': 'First Ever', 'branch_id': SCOPE})
    assert resp.status_code == 200, resp.get_json()
    row = PrintLayout.query.filter_by(name='First Ever').one()
    assert row.is_default is True


def test_the_second_layout_in_that_scope_does_not_become_the_default(client, db_session,
                                                                     main_branch):
    _login(client, _user(db_session, main_branch, 'acct7', 'accountant'), main_branch)
    client.post('/purchase-orders/print-layout/save-as',
               json={'name': 'First Ever', 'branch_id': SCOPE})
    client.post('/purchase-orders/print-layout/save-as',
               json={'name': 'Second Ever', 'branch_id': SCOPE})
    first = PrintLayout.query.filter_by(name='First Ever').one()
    second = PrintLayout.query.filter_by(name='Second Ever').one()
    assert first.is_default is True
    assert second.is_default is False
