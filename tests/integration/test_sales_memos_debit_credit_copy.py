"""BUG-DEBIT-NOTE-CREDIT-COPY-MISMATCH: the shared Credit/Debit Memo form always shows
'Lines to credit' / 'Credit amount' copy, even for a Debit Note."""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


@pytest.fixture(autouse=True)
def _modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('credit_memos', 'debit_memos'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_credit_memo_form_shows_credit_copy(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user, main_branch)
    resp = client.get('/credit-memos/create')
    assert resp.status_code == 200
    assert b'Lines to credit' in resp.data
    assert b'Credit amount' in resp.data
    assert b'Lines to debit' not in resp.data
    assert b'Debit amount' not in resp.data


def test_debit_note_form_shows_debit_copy(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user, main_branch)
    resp = client.get('/debit-notes/create')
    assert resp.status_code == 200
    assert b'Lines to debit' in resp.data
    assert b'Debit amount' in resp.data
    assert b'Lines to credit' not in resp.data
    assert b'Credit amount' not in resp.data
