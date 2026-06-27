import pytest
from werkzeug.exceptions import Forbidden
from app import db
from app.users.models import User
from app.branches.models import Branch
from app.staff_management.scope import (
    accountant_permission_keys, manageable_users, is_in_scope,
    assert_in_scope, merge_branches, merge_permissions,
)

pytestmark = [pytest.mark.unit]


def _branch(code):
    b = Branch(code=code, name=f'{code} Branch', is_active=True)
    db.session.add(b); db.session.flush()
    return b


def _user(role, branches, perms=None):
    u = User(username=f'{role}_{branches[0].code}', email=f'{role}_{branches[0].code}@t.com',
             full_name='U', role=role, is_active=True)
    u.set_password('x')
    if perms is not None:
        u.set_book_permissions(perms)
    db.session.add(u); db.session.flush()
    u.set_branches(branches)
    return u


def test_accountant_permission_keys_only_held(db_session):
    a = _branch('A')
    acct = _user('accountant', [a], {'accounts_payable': True, 'payments': False})
    assert accountant_permission_keys(acct) == {'accounts_payable'}


def test_manageable_users_shared_branch_only(db_session):
    a, b = _branch('A'), _branch('B')
    acct = _user('accountant', [a], {'accounts_payable': True})
    shares = _user('staff', [a])
    other = _user('staff', [b])
    ids = {u.id for u in manageable_users(acct)}
    assert shares.id in ids
    assert other.id not in ids
    assert acct.id not in ids        # accountants are not manageable targets


def test_in_scope_and_assert(db_session):
    a, b = _branch('A'), _branch('B')
    acct = _user('accountant', [a], {})
    inside = _user('viewer', [a])
    outside = _user('viewer', [b])
    assert is_in_scope(acct, inside) is True
    assert is_in_scope(acct, outside) is False
    with pytest.raises(Forbidden):
        assert_in_scope(acct, outside)


def test_merge_branches_preserves_out_of_scope(db_session):
    a, b, c = _branch('A'), _branch('B'), _branch('C')
    acct = _user('accountant', [a, b], {})
    target = _user('staff', [a, c])           # c is outside acct's {a,b}
    # accountant submits only b (drops a, can't see c)
    result_ids = sorted(x.id for x in merge_branches(acct, target, [b.id]))
    assert result_ids == sorted([b.id, c.id])  # b added (in own), c preserved, a removed


def test_merge_branches_rejects_foreign_submission(db_session):
    a, b = _branch('A'), _branch('B')
    acct = _user('accountant', [a], {})
    target = _user('staff', [a])
    # accountant tries to add b (not theirs) via a forged POST → intersected away
    result_ids = [x.id for x in merge_branches(acct, target, [a.id, b.id])]
    assert b.id not in result_ids
    assert a.id in result_ids


def test_merge_permissions_preserves_out_of_scope(db_session):
    a = _branch('A')
    acct = _user('accountant', [a], {'accounts_payable': True, 'payments': True})
    target = _user('staff', [a], {'general_ledger': True})  # GL outside acct's set
    # accountant submits only accounts_payable
    result = merge_permissions(acct, target, ['accounts_payable'])
    assert result.get('accounts_payable') is True
    assert result.get('payments') is not True   # acct has it but didn't grant it
    assert result.get('general_ledger') is True  # preserved (outside acct's set)


def test_merge_permissions_rejects_foreign_key(db_session):
    a = _branch('A')
    acct = _user('accountant', [a], {'accounts_payable': True})
    target = _user('staff', [a], {})
    # forged submission of a key the accountant doesn't hold → intersected away
    result = merge_permissions(acct, target, ['accounts_payable', 'general_ledger'])
    assert result.get('accounts_payable') is True
    assert result.get('general_ledger') is not True
