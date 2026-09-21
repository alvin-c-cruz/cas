"""The PR list's AP/CD chain columns link out; the LINK is not the permission.

purchase_requests/list.html renders the buy-side chain (PR -> PO -> RR -> AP -> CD) as
plain <a> tags with no per-user check, so a purchaser scoped only to the purchasing books
sees AP and CD numbers and can click them. What must hold is that the TARGET refuses:
accounts_payable.view and cash_disbursements.view carry only @login_required, and the
whole of their protection is the app-level enforce_module_access before_request keyed off
MODULE_REGISTRY ('accounts_payable' and, note the name, 'payments').

That indirection is the reason to pin it here. Someone adding a document view is not
obviously reminded that the guard lives in app/__init__.py rather than on the route, and a
registry entry whose key does not match its blueprint name is easy to mis-wire.

Disclosing the NUMBERS is deliberate and was confirmed by the owner on 2026-09-18:
"everyone who has access to PR should be able to see the other columns but correctly
unable to see the actual document". A purchaser needs to know where a requisition got to;
what they must not get is the document behind it. So the split is the design, not an
oversight -- do not "fix" the unconditional link by hiding the column, and do not let
hiding a column ever become the protection. The route gate is the boundary; the last two
tests here pin both halves so neither can be changed by accident.
"""
import pytest

from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def _dashboard_url(app):
    """Resolved, not hardcoded: dashboard.index is mounted at '/', which is easy to assert
    wrongly and easy to move."""
    with app.test_request_context():
        from flask import url_for
        return url_for('dashboard.index')


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _purchaser(db_session, branch, username='purchaser_only'):
    """A staff purchaser: the purchasing books, and deliberately NOT AP or payments."""
    user = User(username=username, email=f'{username}@test.com',
                full_name=username.title(), role='staff', is_active=True)
    user.set_password('testpass123')
    user.set_book_permissions({'purchase_requests': True, 'purchase_orders': True,
                               'receiving_reports': True})
    db_session.add(user)
    db_session.flush()
    user.set_branches([branch])
    db_session.commit()
    return user


def test_purchaser_is_bounced_from_an_ap_document(client, db_session, main_branch, app):
    user = _purchaser(db_session, main_branch)
    _login(client, user, main_branch)
    resp = client.get('/accounts-payable/1')
    assert resp.status_code == 302
    assert resp.headers['Location'] == _dashboard_url(app)


def test_purchaser_is_bounced_from_a_cd_document(client, db_session, main_branch, app):
    """Guards the registry key specifically: cash_disbursements.* is keyed 'payments',
    so a permission dict that said 'cash_disbursements' would grant nothing and, worse,
    a registry entry that said it would silently open the module to everyone."""
    user = _purchaser(db_session, main_branch, 'purchaser_cd')
    _login(client, user, main_branch)
    resp = client.get('/cash-disbursements/1')
    assert resp.status_code == 302
    assert resp.headers['Location'] == _dashboard_url(app)


def test_the_bounce_is_the_module_gate_not_a_missing_record(client, db_session, main_branch):
    """A 404 would pass the assertions above for the wrong reason -- the documents do not
    exist in this fixture. Granting the books must change the outcome; if it does not, the
    tests above prove nothing about permissions."""
    user = _purchaser(db_session, main_branch, 'purchaser_granted')
    user.set_book_permissions({'purchase_requests': True, 'accounts_payable': True,
                               'payments': True})
    db_session.commit()
    _login(client, user, main_branch)
    for path in ('/accounts-payable/1', '/cash-disbursements/1'):
        resp = client.get(path)
        assert resp.status_code != 302, f'{path} still bounced after the book was granted'


def test_the_pr_list_links_out_without_checking_the_viewer(client, db_session, main_branch):
    """Documents the shape the tests above defend: the template has no per-user check, so
    the target route is the only thing standing between a purchaser and an AP document."""
    import re
    src = open('app/purchase_requests/templates/purchase_requests/list.html',
               encoding='utf-8').read()
    for endpoint in ("accounts_payable.view", "cash_disbursements.view"):
        assert f"url_for('{endpoint}'" in src
        # the anchor is not wrapped in any permission conditional
        anchor = re.search(r'\{%-? *if [^%]*%\}\s*<a href="\{\{ url_for\(\'' + endpoint, src)
        assert anchor is None, f'{endpoint} link is now conditional -- update this file'


@pytest.fixture
def _pr_module_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def test_a_purchaser_still_sees_the_ap_and_cd_columns(client, db_session, main_branch,
                                                      _pr_module_on):
    """The other half of the owner's rule, and the reason the link above stays
    unconditional: someone who can read the requisition list can see how far each one got,
    including that it reached AP and CD, even though those documents are closed to them."""
    from datetime import date
    from app.purchase_requests.models import PurchaseRequest
    user = _purchaser(db_session, main_branch, 'purchaser_sees_columns')
    # The table (and therefore its header row) is inside `{% if pr_list %}`, so an empty
    # list would make this test pass for the wrong reason on a hidden column too.
    db_session.add(PurchaseRequest(
        pr_number='PR-TEST-0001', request_date=date.today(), branch_id=main_branch.id,
        status='draft', created_by_id=user.id, reason='chain column visibility'))
    db_session.commit()
    _login(client, user, main_branch)
    resp = client.get('/purchase-requests')
    assert resp.status_code == 200
    body = resp.data.decode()
    assert '<th>AP #</th>' in body
    assert '<th>CD #</th>' in body
