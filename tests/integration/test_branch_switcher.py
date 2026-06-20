"""Sidebar quick branch-switcher (click 'Current Branch' -> dropdown -> POST /select-branch)."""
import pytest
from app.users.models import User
from app.branches.models import Branch

pytestmark = [pytest.mark.integration]


def _setup(db_session, n_branches=2):
    branches = []
    for i in range(n_branches):
        b = Branch(name=f'Branch{i}', code=f'B{i}', is_active=True)
        db_session.add(b)
        branches.append(b)
    db_session.commit()
    u = User(username='swadmin', email='swadmin@t.com', full_name='SW Admin',
             role='admin', is_active=True)
    u.set_password('pass')
    for b in branches:
        u.branches.append(b)
    db_session.add(u)
    db_session.commit()
    return u, branches


def _login(client, branch_id):
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch_id
    client.post('/login', data={'username': 'swadmin', 'password': 'pass'},
                follow_redirects=True)


def test_switcher_lists_other_branches_with_post_form(client, db_session):
    """With >1 accessible branch, the sidebar shows a switch menu containing a
    POST-to-/select-branch form targeting the OTHER branch."""
    u, branches = _setup(db_session, 2)
    _login(client, branches[0].id)
    body = client.get('/branches').get_data(as_text=True)

    # id="..." attrs are markup-only (the CSS classes + JS ids are always emitted)
    assert 'id="branchSwitchMenu"' in body                   # the dropdown is rendered
    assert branches[0].name in body and branches[1].name in body
    assert '/select-branch' in body                          # switch posts here
    assert f'value="{branches[1].id}"' in body               # other branch is a target
    assert 'name="next"' in body                             # carries return URL


def test_switcher_hidden_when_single_branch(client, db_session):
    """A single-branch company has nothing to switch to -> no menu."""
    u, branches = _setup(db_session, 1)
    _login(client, branches[0].id)
    body = client.get('/branches').get_data(as_text=True)
    assert 'id="branchSwitchMenu"' not in body   # widget markup absent (CSS/JS strings remain)
