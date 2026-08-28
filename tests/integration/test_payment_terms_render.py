"""The new term reaches the rendered page, not just the form class.

tests/unit/test_payment_terms_choices.py reads the choices off the UnboundField.
That proves the list is declared; it cannot prove the option survives to the
HTML a user actually opens -- a template rendering the field by hand, or
overriding `choices` in the view, would satisfy the unit test and still show a
six-item dropdown. One GET per form settles it.
"""
import pytest

from app.users.models import User

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.mark.parametrize('url', ['/customers/create', '/vendors/create'])
def test_net_90_renders_in_the_dropdown(client, db_session, admin_user,
                                        main_branch, url):
    _login(client, admin_user, main_branch)
    resp = client.get(url)
    assert resp.status_code == 200
    assert b'Net 90' in resp.data, '%s renders no Net 90 option' % url


@pytest.mark.parametrize('url', ['/customers/create', '/vendors/create'])
def test_the_existing_terms_still_render(client, db_session, admin_user,
                                         main_branch, url):
    """CONTROL. An absence test alone would pass against a 500; this pins that
    the dropdown is really there and merely GAINED an option."""
    _login(client, admin_user, main_branch)
    data = client.get(url).data
    for term in (b'Net 15', b'Net 30', b'Net 45', b'Net 60',
                 b'Cash on Delivery', b'Advance Payment'):
        assert term in data, '%s lost %r' % (url, term)
