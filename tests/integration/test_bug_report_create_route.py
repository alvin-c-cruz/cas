"""POST /bug-reports (spec section 4, and "Three CAS behaviours that would make a report read
'Sent' when nothing was saved")."""
import json
import re

import pytest

from app import db
from app.bug_reports.models import BugReport
from app.users.models import User
from app.users.module_access import default_all_permissions, module_key_for_endpoint
from tests.integration._bug_report_helpers import GIF, PNG, b64, login, payload, post_report

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]


@pytest.fixture
def uploads(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
    return tmp_path


def _report(resp):
    return db.session.get(BugReport, resp.get_json()['id'])


def test_a_signed_in_user_files_a_report(client, accountant_user, main_branch, uploads):
    login(client, accountant_user, 'accountant123', main_branch)
    resp = post_report(client, payload())
    assert resp.status_code == 201
    report = _report(resp)
    assert report.user_id == accountant_user.id
    assert report.message == 'The save button did nothing.'
    context = json.loads(report.context)
    assert context['where']['path'] == '/accounts-payable/12/edit?tab=lines'
    server = context['server']
    assert set(server) == {'user', 'branch', 'company', 'version', 'receivedAt'}
    assert server['user'] == {'id': accountant_user.id, 'username': 'accountant',
                              'full_name': 'Accountant User', 'role': 'accountant'}
    assert server['branch'] == {'id': main_branch.id, 'name': 'Main Office'}
    assert [im.mime for im in report.images] == ['image/jpeg']


def test_the_body_cannot_choose_the_user_or_write_the_server_block(client, accountant_user, staff_user,
                                                                     main_branch, uploads):
    login(client, accountant_user, 'accountant123', main_branch)
    body = payload(user_id=staff_user.id)
    body['context']['server'] = {'user': {'id': staff_user.id}}
    report = _report(post_report(client, body))
    assert report.user_id == accountant_user.id
    assert json.loads(report.context)['server']['user']['id'] == accountant_user.id


def test_signed_out_gets_json_401_not_a_redirect(client, db_session):
    resp = post_report(client, payload())
    assert resp.status_code == 401
    assert resp.get_json() == {'error': 'signed_out'}


def test_a_png_labelled_jpeg_is_stored_as_png(client, accountant_user, main_branch, uploads):
    login(client, accountant_user, 'accountant123', main_branch)
    report = _report(post_report(client, payload(images=[{'kind': 'own', 'mime': 'image/jpeg', 'data': b64(PNG)}])))
    assert report.images[0].mime == 'image/png'
    assert report.images[0].stored_name.endswith('.png')


@pytest.mark.parametrize('change, status, error', [
    ({'message': '   '}, 400, 'bad_message'),
    ({'context': {'pad': 'x' * 64_001}}, 413, 'context_too_large'),
    ({'images': [{'kind': 'page', 'data': b64(GIF)}]}, 400, 'bad_image'),
    ({'images': [{'kind': 'page', 'data': b64(b'\xff\xd8\xff' + b'\x00' * 400_000)}]}, 413, 'image_too_large'),
])
def test_refusals_answer_in_json(client, accountant_user, main_branch, uploads, change, status, error):
    login(client, accountant_user, 'accountant123', main_branch)
    resp = post_report(client, payload(**change))
    assert resp.status_code == status
    assert resp.get_json() == {'error': error}
    assert BugReport.query.count() == 0


def test_a_body_over_two_megabytes_is_refused(client, accountant_user, main_branch, uploads):
    login(client, accountant_user, 'accountant123', main_branch)
    resp = client.post('/bug-reports', data=b'x' * 2_000_001, content_type='application/json')
    assert resp.status_code == 413
    assert resp.get_json() == {'error': 'too_large'}


def test_a_body_that_is_not_json_is_refused(client, accountant_user, main_branch, uploads):
    login(client, accountant_user, 'accountant123', main_branch)
    resp = client.post('/bug-reports', data='hello', content_type='text/plain')
    assert resp.status_code == 400
    assert resp.get_json() == {'error': 'bad_json'}


def test_the_eleventh_report_in_a_day_is_refused(client, accountant_user, main_branch, uploads):
    login(client, accountant_user, 'accountant123', main_branch)
    for _ in range(10):
        assert post_report(client, payload(images=[])).status_code == 201
    resp = post_report(client, payload(images=[]))
    assert resp.status_code == 429
    assert resp.get_json() == {'error': 'too_many'}


def test_a_viewer_can_report(client, viewer_user, main_branch, uploads):
    viewer_user.set_branches([main_branch])  # the viewer fixture has no branch; without one login signs out
    db.session.commit()
    login(client, viewer_user, 'viewer123', main_branch)
    assert post_report(client, payload(images=[])).status_code == 201


def test_a_user_with_no_branch_chosen_can_still_report(client, db_session, main_branch, branch_manila, uploads):
    user = User(username='twobranch', email='two@test.com', full_name='Two Branches',
                role='accountant', is_active=True)
    user.set_password('two-branches-1')
    user.set_book_permissions(default_all_permissions())
    db.session.add(user)
    db.session.flush()
    user.set_branches([main_branch, branch_manila])
    db.session.commit()
    login(client, user, 'two-branches-1')
    with client.session_transaction() as sess:
        sess.pop('selected_branch_id', None)

    page = client.get('/dashboard')
    assert page.status_code == 302 and '/select-branch' in page.headers['Location']  # the gate is live

    resp = post_report(client, payload(images=[]))
    assert resp.status_code == 201
    assert json.loads(_report(resp).context)['server']['branch'] is None


def test_a_user_still_on_the_default_password_can_still_report(client, admin_user, main_branch, uploads,
                                                                app, monkeypatch):
    monkeypatch.setitem(app.config, 'ENFORCE_DEFAULT_PW_CHANGE', True)
    login(client, admin_user, 'admin123', main_branch)  # admin123 is the seeded default

    page = client.get('/dashboard')
    assert page.status_code == 302 and '/profile/change-password' in page.headers['Location']

    assert post_report(client, payload(images=[])).status_code == 201


def test_no_module_gate_applies_to_bug_reports():
    for endpoint in ('bug_reports.create', 'bug_reports.list_reports', 'bug_reports.view_report',
                     'bug_reports.set_status', 'bug_reports.image'):
        assert module_key_for_endpoint(endpoint) is None


def _csrf_token(client):
    html = client.get('/backup').get_data(as_text=True)
    return re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)


def test_a_missing_or_wrong_csrf_token_is_refused_without_signing_the_user_out(client, admin_user, main_branch,
                                                                                uploads, app, monkeypatch):
    login(client, admin_user, 'admin123', main_branch)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    token = _csrf_token(client)

    for headers in ({}, {'X-CSRFToken': 'wrong'}):
        resp = post_report(client, payload(images=[]), headers)
        assert resp.status_code == 400
        assert resp.get_json() == {'error': 'bad_csrf'}

    # Still signed in: the app-wide CSRF handler would have cleared the session and redirected.
    resp = post_report(client, payload(images=[]), {'X-CSRFToken': token})
    assert resp.status_code == 201
