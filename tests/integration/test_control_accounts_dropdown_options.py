"""Every Control Accounts dropdown offers the postable accounts, on a fresh schema.

Plan item 1.5 (2 Nov 2026); work order 2026-07-22-control-accounts-dropdown-empty: on a from-empty
instance, after the first-run admin bootstrap seeded the 27 standard parents and two leaf accounts
were added (114001 Inventory - Trade Goods, 811001 Inventory Adjustment), /settings/control-accounts
showed only "-- not assigned --" in every dropdown, while get_postable_accounts() returned both
leaves in-process. That matters before another client (RIC) is set up on CAS: a new instance must
be able to assign its control accounts through the page.

This pins the server-rendered page itself, which the 22 Jul diagnosis never instrumented: every
dropdown the page draws must carry the blank choice plus every postable account, in code order.
"""
import re

import pytest

from app import db
from app.accounts.models import Account

pytestmark = [pytest.mark.integration, pytest.mark.control_accounts]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _dropdowns(html):
    """{setting name: [option values]} for each control-account <select> on the page."""
    return {m.group(1): re.findall(r'<option value="([^"]*)"', m.group(2))
            for m in re.finditer(r'<select name="([^"]+)" id="ca_[^"]*"[^>]*>(.*?)</select>', html, re.S)}


def _leaf(code, name, parent_code):
    parent = Account.query.filter_by(code=parent_code).one()
    acct = Account(code=code, name=name, account_type=parent.account_type,
                   normal_balance=parent.normal_balance, is_active=True, parent_id=parent.id)
    db.session.add(acct)
    db.session.commit()
    return acct


def _fresh_instance_with_two_leaves():
    from app.seeds.seed_data import seed_standard_parent_accounts
    seed_standard_parent_accounts()                     # what the first-run admin bootstrap seeds
    assert Account.query.count() == 27, 'anti-vacuity: the standard parents were not seeded'
    _leaf('114001', 'Inventory - Trade Goods', '114000')
    _leaf('811001', 'Inventory Adjustment', '811000')


def test_every_dropdown_offers_the_postable_accounts_on_a_fresh_schema(client, db_session, accountant_user):
    from app.posting.control_accounts import get_postable_accounts, visible_control_accounts
    _fresh_instance_with_two_leaves()
    postable = [a.code for a in get_postable_accounts()]
    assert postable == ['114001', '811001']             # the parents are group headers, not choices

    _login(client, 'accountant', 'accountant123')
    resp = client.get('/settings/control-accounts')
    assert resp.status_code == 200
    dropdowns = _dropdowns(resp.get_data(as_text=True))

    expected_names = {setting_key for setting_key, _ in visible_control_accounts().values()}
    assert set(dropdowns) == expected_names and dropdowns, 'every visible control account gets a dropdown'
    for name, values in dropdowns.items():
        assert values == [''] + postable, f'{name} offers {values}'


def test_an_account_added_after_a_first_visit_shows_on_the_next(client, db_session, accountant_user):
    """The 22 Jul sequence: the page was visited, then an account was created, then revisited.
    Nothing may cache the first, empty answer."""
    from app.seeds.seed_data import seed_standard_parent_accounts
    seed_standard_parent_accounts()
    _login(client, 'accountant', 'accountant123')
    first = _dropdowns(client.get('/settings/control-accounts').get_data(as_text=True))
    assert first and all(values == [''] for values in first.values())   # nothing postable yet

    _leaf('114001', 'Inventory - Trade Goods', '114000')
    again = _dropdowns(client.get('/settings/control-accounts').get_data(as_text=True))
    assert all(values == ['', '114001'] for values in again.values())


def test_an_assigned_account_comes_back_selected(client, db_session, accountant_user):
    from app.posting.control_accounts import visible_control_accounts
    _fresh_instance_with_two_leaves()
    _login(client, 'accountant', 'accountant123')
    setting = next(iter(visible_control_accounts().values()))[0]
    form = {name: '' for name, _ in visible_control_accounts().values()}
    form[setting] = '114001'
    client.post('/settings/control-accounts', data=form, follow_redirects=True)
    html = client.get('/settings/control-accounts').get_data(as_text=True)
    block = re.search(r'<select name="%s"[^>]*>(.*?)</select>' % setting, html, re.S).group(1)
    assert re.search(r'<option value="114001"\s+selected>', block)
