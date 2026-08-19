import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.vat_settlement.models import VatSettlement
from tests.integration.test_vat_settlement_compute import _vat_world, _je

pytestmark = [pytest.mark.integration, pytest.mark.vat_settlement]


@pytest.fixture(autouse=True)
def bir_reports_enabled(db_session):
    """/vat-settlement lives behind the OPTIONAL `bir_reports` module.

    Without this every route in this file 404s and each test passes or fails for
    a reason that has nothing to do with VAT -- see test_staff_denied, which was
    asserting "no settlement was created" against a 404.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:bir_reports', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def test_index_renders(client, db_session, main_branch, admin_user):
    _vat_world(main_branch); db.session.commit()
    login(client)
    resp = client.get('/vat-settlement')
    assert resp.status_code == 200
    assert b'VAT Settlement' in resp.data


def test_settle_via_route(client, db_session, main_branch, admin_user):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 50000, 0), (w['ap'].id, 0, 50000)])
    db.session.commit()
    login(client)
    resp = client.post('/vat-settlement/settle',
                       data={'year': '2025', 'quarter': '3'}, follow_redirects=True)
    assert resp.status_code == 200
    s = VatSettlement.query.filter_by(fiscal_year=2025, quarter=3).first()
    assert s is not None and s.status == 'settled'


def test_staff_denied(client, db_session, main_branch, staff_user):
    """Staff cannot settle VAT -- and this must fail for the ROLE reason.

    It previously proved nothing, twice over. With the bir_reports module off
    every route 404'd, so "no settlement was created" was trivially true; and
    even with the module on, staff_user has NO branch assignment, so the
    before_request branch gate force-logged them out and the POST arrived
    ANONYMOUS -- exercising @login_required, never the role check. Mutation
    confirmed it: deleting the role guard from settle() left this test green.

    Hence the setup below opens every OUTER gate deliberately, and the two
    assertions bracket the action: the login really took, and the denial really
    names the role reason rather than some earlier gate's.
    """
    _vat_world(main_branch)
    # Three gates stand between staff and the role check, and each one would
    # deny for its OWN reason, masking whether the role guard works at all:
    #   1. no branch  -> before_request force-logs them out at the picker
    #   2. no book_permission for bir_reports (it is optional + PER-USER)
    #      -> the module gate 302s to / before the view body ever runs
    #   3. the role guard itself -- the only one under test here
    staff_user.branches.append(main_branch)
    perms = dict(staff_user.get_book_permissions() or {})
    perms['bir_reports'] = True
    staff_user.set_book_permissions(perms)
    db.session.commit()

    resp = login(client, 'staff', 'staff123')
    assert b'logout' in resp.data.lower(), (
        'staff never actually logged in, so anything below tests @login_required '
        'rather than the role gate'
    )

    resp = client.post('/vat-settlement/settle',
                       data={'year': '2025', 'quarter': '3'}, follow_redirects=True)

    assert b'Only Accountants and Administrators' in resp.data, (
        'settle did not refuse staff with the role message -- it was blocked by '
        'something else, or not blocked at all'
    )
    assert VatSettlement.query.filter_by(fiscal_year=2025, quarter=3).first() is None


def test_assign_vat_accounts_saves_settings(client, db_session, main_branch, admin_user):
    from app.settings import AppSettings
    from app.accounts.models import Account
    _vat_world(main_branch); db.session.commit()
    login(client)
    pay = Account.query.filter_by(code='20202').first()
    carry = Account.query.filter_by(code='10505').first()
    resp = client.post('/vat-settlement/accounts',
                       data={'vat_payable_account_code': pay.code,
                             'input_vat_carryover_account_code': carry.code},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('vat_payable_account_code') == '20202'
    assert AppSettings.get_setting('input_vat_carryover_account_code') == '10505'


def test_index_prompts_when_unassigned(client, db_session, main_branch, admin_user):
    from app.settings import AppSettings
    _vat_world(main_branch)
    AppSettings.query.filter(AppSettings.key.in_(
        ['vat_payable_account_code', 'input_vat_carryover_account_code'])).delete(
        synchronize_session=False)
    db.session.commit()
    login(client)
    resp = client.get('/vat-settlement')
    assert resp.status_code == 200
    assert b'assign' in resp.data.lower()
