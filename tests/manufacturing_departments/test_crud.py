"""Manufacturing Department CRUD, gating, branch scoping and nav reachability
(R-07 Process Track slice P1).

Mirrors the work_centers package, with ONE deliberate divergence: the edit route
scopes its lookup to the selected branch. work_centers and bank_accounts both fetch
by bare id, which lets a user edit another branch's record by URL -- logged as
BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED. P1 does not fix those; it must
not reproduce the defect, and `test_edit_rejects_another_branchs_record` pins that.
"""
import pytest

from app import db
from app.manufacturing_departments.models import ManufacturingDepartment
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session, on=True):
    AppSettings.set_setting('module_enabled:manufacturing_departments', '1' if on else '0')
    db_session.commit()
    clear_module_config_cache()


def _dept(branch, code='DEPT-1', name='Dehydration'):
    d = ManufacturingDepartment(branch_id=branch.id, code=code, name=name)
    db.session.add(d)
    db.session.commit()
    return d


class TestModuleRegistry:
    def test_registered_with_the_expected_shape(self):
        from app.users.module_access import MODULE_REGISTRY
        entry = next((m for m in MODULE_REGISTRY
                      if m['key'] == 'manufacturing_departments'), None)
        assert entry is not None, 'manufacturing_departments missing from MODULE_REGISTRY'
        assert entry['optional'] is True
        assert entry['default_enabled'] is False, 'must ship default-off'
        assert entry['per_user'] is True
        assert entry['area'] == 'Manufacturing'
        assert entry['group'] == 'Masters'
        assert entry['depends_on'] == []

    def test_endpoint_prefix_resolves_to_this_module(self):
        """Guards the ordering trap in optional-module-gating-traps: a prefix match
        must not resolve this module's endpoints to some other registry entry."""
        from app.users.module_access import module_key_for_endpoint
        assert module_key_for_endpoint('manufacturing_departments.list') == 'manufacturing_departments'
        assert module_key_for_endpoint('manufacturing_departments.create') == 'manufacturing_departments'


class TestModuleGating:
    def test_every_route_404s_when_module_disabled(self, client, db_session, accountant_user, main_branch):
        _enable(db_session, False)
        _login(client, accountant_user, main_branch)
        assert client.get('/manufacturing-departments').status_code == 404
        assert client.get('/manufacturing-departments/create').status_code == 404
        assert client.get('/manufacturing-departments/1/edit').status_code == 404

    def test_list_reachable_when_enabled(self, client, db_session, accountant_user, main_branch):
        _enable(db_session)
        _login(client, accountant_user, main_branch)
        assert client.get('/manufacturing-departments').status_code == 200


class TestCrud:
    def test_create_persists_and_audits(self, client, db_session, accountant_user, main_branch):
        _enable(db_session)
        _login(client, accountant_user, main_branch)
        resp = client.post('/manufacturing-departments/create',
                           data={'code': 'DRY', 'name': 'Dehydration', 'is_active': '1'},
                           follow_redirects=True)
        assert resp.status_code == 200
        d = ManufacturingDepartment.query.filter_by(code='DRY').first()
        assert d is not None
        assert d.branch_id == main_branch.id, 'branch must come from the session, not the form'
        assert d.created_by_id == accountant_user.id

        from app.audit.models import AuditLog
        entry = AuditLog.query.filter_by(module='manufacturing_departments',
                                         record_id=d.id).first()
        assert entry is not None, 'create must write an audit row'
        assert entry.action == 'create'

    def test_edit_updates_and_audits(self, client, db_session, accountant_user, main_branch):
        _enable(db_session)
        d = _dept(main_branch, code='PACK', name='Packing')
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/manufacturing-departments/{d.id}/edit',
                           data={'code': 'PACK', 'name': 'Packing & Sealing', 'is_active': '1'},
                           follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(d)
        assert d.name == 'Packing & Sealing'

        from app.audit.models import AuditLog
        assert AuditLog.query.filter_by(module='manufacturing_departments',
                                        record_id=d.id, action='update').first() is not None

    def test_list_shows_only_the_selected_branch(self, client, db_session, accountant_user,
                                                 main_branch, branch_manila):
        _enable(db_session)
        _dept(main_branch, code='MINE', name='Mine')
        _dept(branch_manila, code='THEIRS', name='Theirs')
        _login(client, accountant_user, main_branch)
        body = client.get('/manufacturing-departments').data
        assert b'MINE' in body
        assert b'THEIRS' not in body

    def test_staff_without_the_module_grant_is_blocked_by_the_module_gate(
            self, client, db_session, staff_user, main_branch):
        """Outer layer: enforce_module_access stops an ungranted user before the view
        ever runs, so this never reaches the role guard below."""
        _enable(db_session)
        staff_user.set_branches([main_branch])
        db_session.commit()
        _login(client, staff_user, main_branch)
        resp = client.post('/manufacturing-departments/create',
                           data={'code': 'NOPE', 'name': 'Nope', 'is_active': '1'},
                           follow_redirects=True)
        assert b'do not have access to this module' in resp.data
        assert ManufacturingDepartment.query.filter_by(code='NOPE').first() is None

    def test_staff_WITH_the_module_grant_is_still_blocked_by_the_role_guard(
            self, client, db_session, staff_user, main_branch):
        """Inner layer -- this is the one that tests THIS view's own `_can_manage()`.
        Without granting the module first, the outer gate masks it entirely and the
        role guard would ship untested."""
        _enable(db_session)
        staff_user.set_branches([main_branch])
        staff_user.set_book_permissions({'manufacturing_departments': True})
        db_session.commit()
        _login(client, staff_user, main_branch)
        resp = client.post('/manufacturing-departments/create',
                           data={'code': 'NOPE2', 'name': 'Nope', 'is_active': '1'},
                           follow_redirects=True)
        assert b'do not have permission to manage' in resp.data
        assert ManufacturingDepartment.query.filter_by(code='NOPE2').first() is None

    def test_edit_rejects_another_branchs_record(self, client, db_session, accountant_user,
                                                 main_branch, branch_manila):
        """THE divergence from work_centers. A bare db.get_or_404(Model, id) would
        hand back branch B's record here -- that is the open bug this slice refuses
        to reproduce."""
        _enable(db_session)
        other = _dept(branch_manila, code='OTHER', name='Other Branch Dept')
        _login(client, accountant_user, main_branch)
        assert client.get(f'/manufacturing-departments/{other.id}/edit').status_code == 404


class TestNavReachability:
    def test_sidebar_links_to_the_list_when_enabled(self, client, db_session,
                                                    accountant_user, main_branch):
        """A route-level GET proves the route works, NOT that a user can reach it
        (feedback-premerge-uitest-gate). Pin the nav link itself."""
        _enable(db_session)
        _login(client, accountant_user, main_branch)
        body = client.get('/manufacturing-departments').data
        assert b'href="/manufacturing-departments"' in body

    def test_sidebar_hides_the_link_when_disabled(self, client, db_session,
                                                  accountant_user, main_branch):
        _enable(db_session, False)
        _login(client, accountant_user, main_branch)
        body = client.get('/dashboard').data
        assert b'href="/manufacturing-departments"' not in body
