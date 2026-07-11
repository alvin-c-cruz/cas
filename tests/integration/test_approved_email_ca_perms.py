"""A Chief Accountant has full access (has_full_access bypasses book_permissions),
so the Access-Permissions grid is inert for that position. The approved email must
store NO book permissions even if book_* boxes are posted. BUG-CA-ACCESS-GRID-POINTLESS."""
import pytest
from app.users.approved_emails import ApprovedEmail

pytestmark = [pytest.mark.integration]


def _login(client, user, branch, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def test_ca_approved_email_stores_no_book_permissions(client, db_session, admin_user, main_branch):
    _login(client, admin_user, main_branch, 'admin123')
    resp = client.post('/approved-emails/add', data={
        'email': 'ca.perm@example.ph', 'position': 'chief_accountant',
        'branch_ids': [str(main_branch.id)],
        'book_accounts_payable': '1',
        'book_general_ledger': '1',
    }, follow_redirects=False)
    assert resp.status_code == 302

    ae = ApprovedEmail.query.filter_by(email='ca.perm@example.ph').first()
    assert ae is not None
    assert ae.role == 'chief_accountant'
    assert not any(ae.get_book_permissions().values()), \
        'Chief Accountant approved email must store no book permissions'
