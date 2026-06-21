"""COA list renders in hierarchical (pre-order DFS) order.

The legacy leaf codes interleave across groups (a child's code can sort before
its parent's, or among another group's children). A flat code-sort therefore
scatters children away from their parent. The list view must instead emit each
root group, then its children (recursively), so a subtree is contiguous and the
depth indentation tells the truth.
"""
import re
import pytest
from app.accounts.models import Account

pytestmark = [pytest.mark.accounts, pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def test_list_is_hierarchical_not_flat_code_order(client, db_session,
                                                  accountant_user, main_branch):
    login(client)
    # Two parents; each has a child whose code interleaves under a flat sort:
    # flat code order would be 10201, 11000, 11500, 12000 (child-before-parent).
    p1 = Account(code='11000', name='Cash Grp', account_type='Asset',
                 normal_balance='debit', classification='Current')
    p2 = Account(code='12000', name='Recv Grp', account_type='Asset',
                 normal_balance='debit', classification='Current')
    db_session.add_all([p1, p2])
    db_session.commit()
    c1 = Account(code='11500', name='Cash Child', account_type='Asset',
                 normal_balance='debit', parent_id=p1.id)
    c2 = Account(code='10201', name='Recv Child', account_type='Asset',
                 normal_balance='debit', parent_id=p2.id)
    db_session.add_all([c1, c2])
    db_session.commit()

    resp = client.get('/accounts/')
    assert resp.status_code == 200
    codes = re.findall(r'data-code="([^"]+)"', resp.data.decode())

    # pre-order DFS: each parent immediately followed by its child
    assert codes == ['11000', '11500', '12000', '10201']
