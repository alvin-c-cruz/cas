"""By-id routes on `accessible_ids`-scoped modules must not serve an inaccessible branch's record.

BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED, second sub-shape. The LIST
route filters on `get_accessible_branches(current_user)` -- a SET -- while the
by-id fetch is a bare `db.get_or_404(Model, id)`. `before_request` validates the
SELECTED branch is accessible; it never checks the FETCHED record's branch.

THIS SHAPE IS NOT THE ONE ALREADY FIXED, and the difference is the whole point.
`work_centers`/`bank_accounts`/`petty_cash` scope to the ONE
`session['selected_branch_id']`, so `_get_scoped()` (filter id + that branch) is
exact for them. Here the list is scoped to every branch the user can reach, so
the guard must be set MEMBERSHIP. Copying `_get_scoped()` into these modules
would be a REGRESSION: it would hide records the user is entitled to open,
namely any assigned branch that is not the currently-selected one.
`test_second_assigned_branch_is_not_refused` below is what pins that distinction.

WHY THE USER IS AN ACCOUNTANT AND NEVER admin: `get_accessible_branches` returns
ALL active branches for a full-access user (admin / chief accountant), so admin
crossing a branch boundary is CORRECT behaviour, not the bug. A test driven as
admin cannot fail here no matter how broken the guard is. The existing
`test_branch_scoped_byid_fetch.py` uses admin because the selected-branch shape
does constrain admins; this shape does not.

Every test issues a REAL request -- a unit assertion on the query object would
pass against the vulnerable code, because it never exercises the route's own
lookup, which IS the defect.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.fixed_assets.models import FixedAsset
from app.fixed_asset_depreciation.models import DepreciationRun
from app.settings import AppSettings
from app.withholding_certificates.models import WithholdingCertificateReceived

pytestmark = [pytest.mark.integration]


MODULE_KEYS = ('fixed_assets', 'fixed_asset_depreciation', 'bir_reports')


@pytest.fixture(autouse=True)
def _enable_modules(db_session):
    """Open BOTH gates, instance and per-user, or this whole file is vacuous.

    Without the instance flag the module gate bounces every route here and every
    cross-branch assertion passes for the wrong reason -- green against the
    vulnerable code, proving nothing. That exact trap made 13 tests pass on the
    previous sub-shape. The `test_control_*` cases are the tripwire: they assert
    200 on an OWN-branch record, so a closed gate fails loudly instead of letting
    the denial tests fake success. (memory feedback-outer-gate-masks-inner-guard)

    `withholding_certificates.*` endpoints belong to `bir_reports`, not a key of
    their own -- see MODULE_REGISTRY.

    Clearing the cache on the way OUT is not tidiness, it is required. The
    `module_enabled:` override is memoized for an hour on the SESSION-scoped app,
    while `db_session` drops the rows after each test -- so without the teardown
    the cached '1' outlives the data and leaks into later tests. Proved, not
    assumed: `test_module_enablement.py` passes alone and its
    `test_bir_defaults_disabled` FAILED when this file ran first. Same class as
    BUG-TEST-MODULE-CACHE-LEAK-ORDER-MONITORING.
    """
    from app.utils.cache_helpers import clear_module_config_cache
    for key in MODULE_KEYS:
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    clear_module_config_cache()   # module_enabled reads a 1h-memoized override
    yield
    clear_module_config_cache()


@pytest.fixture(autouse=True)
def _grant_optional_modules_to_accountant(db_session, accountant_user):
    """Give the branch-limited user access to modules the permission grid omits.

    NOT test scaffolding for its own sake -- it is what makes this guard
    reachable, and the reason deserves recording. All three keys are `optional`
    WITHOUT `per_user`, so `all_permission_keys()` leaves them out of the grid
    and `default_all_permissions()` never grants them. `can_access_module` then
    falls through to `book_permissions.get(key, False)` -> False for anyone who
    is not full-access. Net effect TODAY: only admin/chief-accountant can open
    these routes, and those roles reach every branch legitimately -- so the
    cross-branch defect is currently UNREACHABLE in production.

    It is one word from being reachable. Adding `per_user: True` to any of these
    registry entries -- precisely what was already done for `employees`,
    `products` and `units_of_measure` -- puts a branch-limited user on these
    routes with no other change, and the hole opens instantly. This fixture
    simulates that state so the guard is proven now rather than after the fact.
    """
    perms = accountant_user.get_book_permissions()
    perms.update({k: True for k in MODULE_KEYS})
    accountant_user.set_book_permissions(perms)
    db_session.commit()


def _login_accountant(client):
    return client.post('/login',
                       data={'username': 'accountant', 'password': 'accountant123'},
                       follow_redirects=True)


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _assert_denied(response, what):
    """404 specifically -- not "any non-200", and not a 3xx.

    A redirect is what an unrelated flash-and-bounce produces (a missing
    control account, a status guard), so accepting 3xx would let a vulnerable
    route look guarded. That precise mistake made a petty-cash test unable to
    fail on the previous sub-shape.
    """
    assert response.status_code == 404, (
        '%s was not refused across the branch boundary (status %s)'
        % (what, response.status_code))


def _make_asset(db_session, branch, make_account, code):
    """A FixedAsset needs THREE accounts, not one: cost, accumulated
    depreciation and depreciation expense are all NOT NULL."""
    asset = FixedAsset(
        branch_id=branch.id, code=code, name='Asset %s' % code,
        acquisition_source_type='opening', acquisition_date=date(2026, 1, 1),
        acquisition_cost=Decimal('100000.00'),
        cost_account_id=make_account('15%s' % code[-2:]).id,
        accumulated_depreciation_account_id=make_account('16%s' % code[-2:]).id,
        depreciation_expense_account_id=make_account('65%s' % code[-2:]).id,
        depreciation_method='straight_line', salvage_value=Decimal('0.00'))
    db_session.add(asset)
    db_session.commit()
    return asset


def _make_run(db_session, branch, year=2026, month=1):
    run = DepreciationRun(branch_id=branch.id, period_year=year,
                          period_month=month, status='posted')
    db_session.add(run)
    db_session.commit()
    return run


def _make_cert(db_session, branch, customer, wht, number):
    cert = WithholdingCertificateReceived(
        branch_id=branch.id, customer_id=customer.id, certificate_number=number,
        date_received=date(2026, 3, 31), period_from=date(2026, 1, 1),
        period_to=date(2026, 3, 31), wt_id=wht.id,
        income_payment=Decimal('50000.00'), tax_withheld=Decimal('500.00'))
    db_session.add(cert)
    db_session.commit()
    return cert


@pytest.fixture
def wht_code(db_session):
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC158', name='Test WHT', rate=Decimal('1.00'),
                        is_active=True)
    db_session.add(wt)
    db_session.commit()
    return wt


# ── fixed_assets ────────────────────────────────────────────────────────────

class TestFixedAssets:

    def test_view_does_not_serve_an_inaccessible_branchs_asset(
            self, client, db_session, accountant_user, main_branch, branch_manila,
            make_account):
        other = _make_asset(db_session, branch_manila, make_account, 'FA-OTHER')
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        _assert_denied(client.get('/fixed-assets/%d' % other.id), 'fixed asset view')

    def test_edit_get_does_not_serve_an_inaccessible_branchs_asset(
            self, client, db_session, accountant_user, main_branch, branch_manila,
            make_account):
        other = _make_asset(db_session, branch_manila, make_account, 'FA-OTHR2')
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        _assert_denied(client.get('/fixed-assets/%d/edit' % other.id), 'fixed asset edit')

    def test_delete_does_not_remove_an_inaccessible_branchs_asset(
            self, client, db_session, accountant_user, main_branch, branch_manila,
            make_account):
        other = _make_asset(db_session, branch_manila, make_account, 'FA-OTHR3')
        asset_id = other.id
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        client.post('/fixed-assets/%d/delete' % asset_id, follow_redirects=True)
        db_session.expire_all()
        assert db_session.get(FixedAsset, asset_id) is not None, (
            'cross-branch POST deleted the asset')

    def test_control_own_branch_view_still_works(
            self, client, db_session, accountant_user, main_branch, make_account):
        """Guard must not break the legitimate path -- AND proves the 404s above
        are the branch guard, not the module gate 404ing everything."""
        mine = _make_asset(db_session, main_branch, make_account, 'FA-MINE')
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        assert client.get('/fixed-assets/%d' % mine.id).status_code == 200

    def test_second_assigned_branch_is_not_refused(
            self, client, db_session, accountant_user, main_branch, branch_manila,
            make_account):
        """THE test that separates this shape from the selected_branch_id one.

        The user is assigned BOTH branches but has branch A selected. A
        `_get_scoped()`-style guard (id + selected branch) would 404 this, which
        would be a regression: the list route shows this record, so the detail
        page must open. Only set-membership against accessible branches is right.
        """
        accountant_user.set_branches([main_branch, branch_manila])
        db_session.commit()
        theirs = _make_asset(db_session, branch_manila, make_account, 'FA-BOTH')
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        assert client.get('/fixed-assets/%d' % theirs.id).status_code == 200, (
            'a record in a DIFFERENT-but-assigned branch was refused -- the guard '
            'is single-branch equality, not accessible-set membership')


# ── fixed_asset_depreciation ────────────────────────────────────────────────

class TestDepreciationRun:

    def test_reverse_does_not_reach_an_inaccessible_branchs_run(
            self, client, db_session, accountant_user, main_branch, branch_manila):
        other = _make_run(db_session, branch_manila)
        run_id = other.id
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        r = client.post('/fixed-asset-depreciation/%d/reverse' % run_id)
        _assert_denied(r, 'depreciation run reverse')
        db_session.expire_all()
        assert db_session.get(DepreciationRun, run_id).status == 'posted', (
            'cross-branch POST changed the run status')

    def test_control_own_branch_run_is_reachable(
            self, client, db_session, accountant_user, main_branch):
        """Own-branch run must NOT 404. Asserting `!= 404` rather than a specific
        code on purpose: reversal has its own business guards (period locks,
        control accounts) that may legitimately refuse with a flash+redirect.
        What must never happen is the not-found that means the branch guard ate it."""
        mine = _make_run(db_session, main_branch, month=2)
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        assert client.post('/fixed-asset-depreciation/%d/reverse' % mine.id
                           ).status_code != 404


# ── withholding_certificates ────────────────────────────────────────────────

class TestWithholdingCertificates:

    def test_edit_get_does_not_serve_an_inaccessible_branchs_certificate(
            self, client, db_session, accountant_user, main_branch, branch_manila,
            customer, wht_code):
        other = _make_cert(db_session, branch_manila, customer, wht_code, 'WC-OTHER')
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        _assert_denied(client.get('/withholding-certificates/%d/edit' % other.id),
                       'withholding certificate edit')

    def test_delete_does_not_remove_an_inaccessible_branchs_certificate(
            self, client, db_session, accountant_user, main_branch, branch_manila,
            customer, wht_code):
        other = _make_cert(db_session, branch_manila, customer, wht_code, 'WC-OTHR2')
        cert_id = other.id
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        client.post('/withholding-certificates/%d/delete' % cert_id,
                    follow_redirects=True)
        db_session.expire_all()
        assert db_session.get(WithholdingCertificateReceived, cert_id) is not None, (
            'cross-branch POST deleted the certificate')

    def test_control_own_branch_edit_still_works(
            self, client, db_session, accountant_user, main_branch, customer, wht_code):
        mine = _make_cert(db_session, main_branch, customer, wht_code, 'WC-MINE')
        _login_accountant(client)
        _select_branch(client, main_branch.id)
        assert client.get('/withholding-certificates/%d/edit' % mine.id
                          ).status_code == 200
