"""Purchase Requisition: the Date Needed header field.

When the goods are wanted by -- distinct from Request Date, which is when the
requisition was raised. Optional and unvalidated by owner directive (2026-08-14):
it matches how the paper form behaves, and mirrors Expected Date on the Purchase
Order, which is also optional and unchecked.

The column is nullable and MUST stay that way: requisitions already exist in
PhilGen's live database and in two local imports, and a NOT NULL column would
need a date invented for them.

Assertions are made on RENDERS, not only on POST contracts -- a field dropped
from a template is invisible to a test that supplies the field itself (memory
`csrf-only-render-drops-hidden-fields`).
"""
from datetime import date

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_requests', 'units_of_measure'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def pr(db_session, admin_user, main_branch):
    p = PurchaseRequest(pr_number='DN-1', request_date=date(2026, 8, 14),
                        date_needed=date(2026, 8, 30), branch_id=main_branch.id,
                        status='draft', created_by_id=admin_user.id)
    db_session.add(p)
    db_session.commit()
    return p


class TestTheColumn:

    def test_it_is_nullable(self, db_session, admin_user, main_branch):
        """A requisition with no date needed must be storable -- the live rows
        that predate this field have none."""
        p = PurchaseRequest(pr_number='DN-NULL', request_date=date(2026, 8, 14),
                            branch_id=main_branch.id, status='draft',
                            created_by_id=admin_user.id)
        db_session.add(p)
        db_session.commit()
        assert p.date_needed is None

    def test_it_is_in_the_amendment_snapshot(self):
        """Without this an amendment that changes the date records nothing, so a
        revision cannot say what was altered."""
        assert 'date_needed' in PurchaseRequest.SNAPSHOT_HEADER_FIELDS

    def test_to_dict_exposes_it(self, pr):
        assert pr.to_dict()['date_needed'] == '2026-08-30'

    def test_to_dict_handles_a_missing_date(self, db_session, admin_user, main_branch):
        p = PurchaseRequest(pr_number='DN-NULL2', request_date=date(2026, 8, 14),
                            branch_id=main_branch.id, status='draft',
                            created_by_id=admin_user.id)
        db_session.add(p)
        db_session.commit()
        assert p.to_dict()['date_needed'] is None


class TestTheFormRendersIt:

    def test_create_form_renders_the_field(self, client, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-requests/create').data.decode()
        assert 'name="date_needed"' in html, 'the input is not rendered at all'
        assert 'Date Needed' in html, 'the label is missing'

    def test_edit_form_prefills_the_stored_date(self, client, admin_user, main_branch, pr):
        """A round-trip check: an edit form that renders the input but not its
        value silently blanks the field on the next save."""
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}/edit').data.decode()
        assert 'name="date_needed"' in html
        assert '2026-08-30' in html


class TestItRoundTrips:

    def _payload(self, **over):
        data = {'pr_number': 'DN-NEW', 'request_date': '2026-08-14',
                'date_needed': '2026-09-01', 'reason': 'boiler',
                'line_items': '[{"description": "Gasket", "quantity": "2"}]'}
        data.update(over)
        return data

    def test_create_persists_it(self, client, db_session, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        resp = client.post('/purchase-requests/create', data=self._payload(),
                           follow_redirects=True)
        assert resp.status_code == 200

        p = PurchaseRequest.query.filter_by(pr_number='DN-NEW').first()
        assert p is not None, 'the requisition was not created at all'
        assert p.date_needed == date(2026, 9, 1)

    def test_create_without_it_is_accepted(self, client, db_session, admin_user, main_branch):
        """Control: the field is OPTIONAL. Leaving it blank must not become a
        validation error -- and must not block a requisition being raised."""
        _login(client, admin_user, main_branch)
        resp = client.post('/purchase-requests/create',
                           data=self._payload(pr_number='DN-BLANK', date_needed=''),
                           follow_redirects=True)
        assert resp.status_code == 200

        p = PurchaseRequest.query.filter_by(pr_number='DN-BLANK').first()
        assert p is not None, 'a blank date needed blocked the save'
        assert p.date_needed is None

    def test_a_date_before_the_request_date_is_accepted(self, client, db_session,
                                                        admin_user, main_branch):
        """Control for the deliberate absence of validation (owner directive).
        If someone later adds an ordering rule, this is the test that should be
        changed on purpose rather than silently."""
        _login(client, admin_user, main_branch)
        client.post('/purchase-requests/create',
                    data=self._payload(pr_number='DN-EARLY', date_needed='2026-08-01'),
                    follow_redirects=True)
        p = PurchaseRequest.query.filter_by(pr_number='DN-EARLY').first()
        assert p is not None and p.date_needed == date(2026, 8, 1)

    def test_edit_updates_it(self, client, db_session, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        resp = client.post(f'/purchase-requests/{pr.id}/edit', data={
            'pr_number': 'DN-1', 'request_date': '2026-08-14',
            'date_needed': '2026-10-05', 'reason': 'WITNESS-EDIT',
            'row_version': pr.row_version,
            'line_items': '[{"description": "Gasket", "quantity": "2"}]',
        }, follow_redirects=True)
        assert resp.status_code == 200

        p = db.session.get(PurchaseRequest, pr.id)
        assert p.reason == 'WITNESS-EDIT', 'the edit never applied -- the date '
        assert p.date_needed == date(2026, 10, 5)

    def test_edit_can_clear_it(self, client, db_session, admin_user, main_branch, pr):
        """Blanking the field must actually clear it, not leave the old value."""
        _login(client, admin_user, main_branch)
        client.post(f'/purchase-requests/{pr.id}/edit', data={
            'pr_number': 'DN-1', 'request_date': '2026-08-14',
            'date_needed': '', 'reason': 'WITNESS-CLEAR',
            'row_version': pr.row_version,
            'line_items': '[{"description": "Gasket", "quantity": "2"}]',
        }, follow_redirects=True)

        p = db.session.get(PurchaseRequest, pr.id)
        assert p.reason == 'WITNESS-CLEAR'
        assert p.date_needed is None


class TestItIsVisible:

    def test_the_detail_page_shows_it(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'Date Needed' in html
        assert 'Aug 30, 2026' in html

    def test_the_printout_shows_it(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}/print').data.decode()
        assert 'Date Needed' in html
        assert 'August 30, 2026' in html

    def test_surfaces_survive_a_missing_date(self, client, db_session, admin_user,
                                             main_branch):
        """Control: every existing requisition has none. Detail and print must
        still render rather than 500 on a None.strftime."""
        p = PurchaseRequest(pr_number='DN-NONE', request_date=date(2026, 8, 14),
                            branch_id=main_branch.id, status='draft',
                            created_by_id=admin_user.id)
        db_session.add(p)
        db_session.commit()
        _login(client, admin_user, main_branch)

        assert client.get(f'/purchase-requests/{p.id}').status_code == 200
        assert client.get(f'/purchase-requests/{p.id}/print').status_code == 200
