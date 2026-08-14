"""Master-data list search boxes must carry a visible submit button.

Vendors, Customers and Employees share one copy-pasted `.search-box` block that
rendered a lone text input inside a GET form -- no button, no as-you-type
filtering. The search WORKED (pressing Enter submits, and the server-side `q`
filter is correct), but nothing on screen said so, and a 150-vendor list looked
broken to the user who reported it.

It is specifically an INCONSISTENCY: nine of the twelve list pages with a search
box (AP, CDV, CRV, DR, PO, PR, RR, SI, SO) already render a submit button, so
anyone who learns the search on a document list and then opens Vendors concludes
the control is broken.

These assert the BUTTON is inside the search FORM -- not merely somewhere on the
page. A `<button>` elsewhere in the document (the page-actions bar, a row's
Delete form) would satisfy a naive `b'<button' in resp.data` while leaving the
search box exactly as unusable as before.
"""
import re

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.views]

PAGES = [
    ('vendors', '/vendors'),
    ('customers', '/customers'),
    ('employees', '/employees'),
]


@pytest.fixture(autouse=True)
def _enable_employees(db_session):
    """`employees` is an OPTIONAL module; with it off, a before_request hook
    abort(404)s the page and every assertion here would fail on a 404 rather
    than on the markup. Vendors and Customers are core and need no flag.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:employees', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    """`selected_branch_id` is REQUIRED. Without it a `before_request` hook
    redirects every page to /select-branch, and each assertion below then fails
    on an empty redirect body -- red for a reason that has nothing to do with
    the button, which is how a green-after-fix run could prove nothing.
    """
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _form_or_fail(client, url, name):
    """Fetch the page, insist it actually rendered, and return its search form."""
    resp = client.get(url)
    assert resp.status_code == 200, f'{name}: GET {url} -> {resp.status_code}'
    form = _search_form(resp.data.decode())
    assert form is not None, f'{name}: no GET form owning the q input'
    return form


def _search_form(html):
    """The GET form that owns the `q` input, or None.

    Non-greedy to the FIRST closing tag so a later form on the page cannot be
    swept into the match and lend it a button it does not own.
    """
    for m in re.finditer(r'<form[^>]*\bmethod=["\']get["\'][^>]*>(.*?)</form>',
                         html, re.S | re.I):
        if 'name="q"' in m.group(1):
            return m.group(1)
    return None


class TestSearchFormHasASubmitButton:

    @pytest.mark.parametrize('name,url', PAGES)
    def test_search_form_contains_a_submit_button(self, client, admin_user,
                                                  main_branch, name, url):
        _login(client, admin_user, main_branch)
        form = _form_or_fail(client, url, name)
        assert re.search(r'<button[^>]*type=["\']submit["\']', form, re.I), (
            f'{name}: search form has no submit button -- the only way to run a '
            f'search is an Enter keypress the UI never advertises')

    @pytest.mark.parametrize('name,url', PAGES)
    def test_the_button_is_labelled_search(self, client, admin_user,
                                           main_branch, name, url):
        """An unlabelled or icon-only button reintroduces the same problem.

        Reads the label out of the BUTTON element, not the surrounding form. A
        plain `'Search' in form` passes vacuously: every one of these inputs has
        placeholder="Search by ...", so the word is present whether or not a
        button exists. Mutation-proven -- with the button deleted, the loose form
        of this assertion still went green.
        """
        _login(client, admin_user, main_branch)
        form = _form_or_fail(client, url, name)
        m = re.search(r'<button[^>]*type=["\']submit["\'][^>]*>(.*?)</button>',
                      form, re.S | re.I)
        assert m, f'{name}: no submit button in the search form'
        assert 'Search' in m.group(1), (
            f'{name}: submit button label is {m.group(1).strip()!r}, not Search')

    @pytest.mark.parametrize('name,url', PAGES)
    def test_the_q_input_survives(self, client, admin_user, main_branch, name, url):
        """Control: adding the button must not disturb the field it submits."""
        _login(client, admin_user, main_branch)
        assert 'name="q"' in _form_or_fail(client, url, name)


class TestSearchStillFilters:
    """Control: the button is a UI addition. The server-side filter these pages
    already had must behave exactly as before -- if one of these regresses, the
    'fix' broke the thing it was meant to make usable."""

    def test_vendor_search_still_filters(self, client, admin_user, main_branch,
                                         db_session):
        from app.vendors.models import Vendor
        db_session.add_all([
            Vendor(code='V900', name='ALPHA TRADING', is_active=True),
            Vendor(code='V901', name='BETA SUPPLY', is_active=True),
        ])
        db_session.commit()
        _login(client, admin_user, main_branch)

        resp = client.get('/vendors?q=ALPHA')
        assert resp.status_code == 200
        assert b'ALPHA TRADING' in resp.data
        assert b'BETA SUPPLY' not in resp.data

    def test_vendor_search_is_case_insensitive(self, client, admin_user,
                                               main_branch, db_session):
        from app.vendors.models import Vendor
        db_session.add(Vendor(code='V902', name='GAMMA WORKS', is_active=True))
        db_session.commit()
        _login(client, admin_user, main_branch)

        assert b'GAMMA WORKS' in client.get('/vendors?q=gamma').data

    def test_blank_query_lists_everything(self, client, admin_user, main_branch,
                                          db_session):
        from app.vendors.models import Vendor
        db_session.add_all([
            Vendor(code='V903', name='DELTA CO', is_active=True),
            Vendor(code='V904', name='EPSILON CO', is_active=True),
        ])
        db_session.commit()
        _login(client, admin_user, main_branch)

        data = client.get('/vendors').data
        assert b'DELTA CO' in data and b'EPSILON CO' in data
