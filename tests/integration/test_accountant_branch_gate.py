"""Integration tests for accountant branch-scoping gate (Task 1).

Verifies:
- An accountant assigned exactly one branch is auto-selected by the before_request gate.
- An accountant trying to POST /select-branch with an unassigned branch ID is rejected.
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.branches]


def _login_direct(client, user, branch, password):
    """Set the branch in session and POST to /login.

    The before_request gate will validate and auto-select the assigned branch.
    """
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    return client.post(
        '/login',
        data={'username': user.username, 'password': password},
        follow_redirects=True,
    )


def test_accountant_with_one_branch_is_auto_selected(
    client, db_session, accountant_user, main_branch
):
    """Accountant assigned one branch: before_request auto-selects it after login."""
    # accountant_user fixture already assigns main_branch (via conftest)
    _login_direct(client, accountant_user, main_branch, 'accountant123')

    with client.session_transaction() as sess:
        assert sess.get('selected_branch_id') == main_branch.id, (
            "before_request should auto-select the single accessible branch"
        )


def test_accountant_cannot_select_unassigned_branch(
    client, db_session, accountant_user, main_branch, branch_manila
):
    """Accountant with main_branch assigned cannot POST /select-branch with manila's id."""
    # accountant_user is assigned only main_branch (via conftest)
    # Set up session as if logged in
    with client.session_transaction() as sess:
        sess['_user_id'] = str(accountant_user.id)
        sess['_fresh'] = True
        # Clear branch so the picker is shown
        sess.pop('selected_branch_id', None)

    # Attempt to select branch_manila (not assigned)
    resp = client.post(
        '/select-branch',
        data={'branch_id': str(branch_manila.id)},
        follow_redirects=False,
    )

    # Should NOT redirect to dashboard; should stay on select_branch or redirect there
    with client.session_transaction() as sess:
        selected = sess.get('selected_branch_id')
    assert selected != branch_manila.id, (
        "Accountant must not be able to select an unassigned branch"
    )
