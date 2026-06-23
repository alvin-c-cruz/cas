"""Integration tests for account form rich type choices + conditional classification.

Task 7: account_type expanded to 11 values; DEFAULT_NORMAL_BALANCE auto-applied;
Asset/Liability require a classification; other types do not.

Uses accountant_user (sole accountant) so the create request is auto-approved
and an Account row is written immediately — admin goes to pending only.
"""
import pytest
from app.accounts.models import Account
from app.audit.models import AuditLog
pytestmark = [pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def test_create_cogs_account(client, db_session, accountant_user, main_branch):
    """Cost of Goods Sold account: auto-approved; normal_balance defaults to debit."""
    accountant_user.add_branch(main_branch)
    login(client)
    resp = client.post('/accounts/create', data={
        'code': '50101',
        'name': 'Cost of Goods Sold',
        'account_type': 'Cost of Goods Sold',
        'classification': '',
        'description': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    a = Account.query.filter_by(code='50101').first()
    assert a is not None, "Account row not created (check approval path)"
    assert a.account_type == 'Cost of Goods Sold'
    assert a.normal_balance == 'debit'   # defaulted from DEFAULT_NORMAL_BALANCE

    # Audit log must exist for the create action
    audit = AuditLog.query.filter_by(module='account', action='create').first()
    assert audit is not None, "No audit log row for account create"


def test_asset_requires_classification(client, db_session, accountant_user, main_branch):
    """Asset without classification is rejected; no Account row created and flash shown."""
    import html
    accountant_user.add_branch(main_branch)
    login(client)
    resp = client.post('/accounts/create', data={
        'code': '10199',
        'name': 'Some Asset',
        'account_type': 'Asset',
        'classification': '',
        'description': '',
    }, follow_redirects=True)
    # Should re-render (200) with an error flash; no Account row created
    assert Account.query.filter_by(code='10199').first() is None
    body = html.unescape(resp.data.decode())
    assert 'Classification (Current or Non-Current) is required for Asset and Liability accounts.' in body


def test_asset_with_classification_persists(client, db_session, accountant_user, main_branch):
    """Asset with Current classification is accepted; classification + normal_balance stored."""
    accountant_user.add_branch(main_branch)
    login(client)
    client.post('/accounts/create', data={
        'code': '10199',
        'name': 'Some Asset',
        'account_type': 'Asset',
        'classification': 'Current',
        'description': '',
    }, follow_redirects=True)
    a = Account.query.filter_by(code='10199').first()
    assert a is not None, "Account row not created"
    assert a.classification == 'Current'
    assert a.normal_balance == 'debit'   # Asset defaults to debit


def test_edit_asset_without_classification_rejected(client, db_session, accountant_user, main_branch):
    """Edit route: submitting Asset with blank classification is rejected; existing value unchanged."""
    import html
    accountant_user.add_branch(main_branch)
    login(client)

    # First create a valid Asset account (auto-approved as sole accountant)
    client.post('/accounts/create', data={
        'code': '10201',
        'name': 'Test Asset Account',
        'account_type': 'Asset',
        'classification': 'Current',
        'description': '',
    }, follow_redirects=True)
    account = Account.query.filter_by(code='10201').first()
    assert account is not None, "Setup failed: Asset account not created"
    assert account.classification == 'Current'

    # Now POST to edit route with no classification — should be rejected
    resp = client.post(f'/accounts/{account.id}/edit', data={
        'code': '10201',
        'name': 'Test Asset Account',
        'account_type': 'Asset',
        'classification': '',
        'description': '',
        'request_reason': 'testing edit guard',
    }, follow_redirects=True)

    assert resp.status_code == 200
    body = html.unescape(resp.data.decode())
    assert 'Classification (Current or Non-Current) is required for Asset and Liability accounts.' in body

    # Classification must remain unchanged
    from app import db
    db.session.refresh(account)
    assert account.classification == 'Current', "Classification was incorrectly blanked on edit"
