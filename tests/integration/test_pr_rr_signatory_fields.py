"""PR and RR carry their own printed signatories, like PurchaseOrder.

Owner directive 2026-08-21. They previously printed from ONE company-wide
setting, so a one-off signatory became permanent for every future printout.

THE FALLBACK IS THE LOAD-BEARING PART. The company setting does not go away: it
seeds a new document, and the printout falls back to it PER SLOT. Without that,
every document saved before this shipped would print three blank ruled lines
instead of the configured names -- a silent regression on exactly the installs
that had bothered to configure signatories.
"""
from datetime import date

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def _open_gates(db_session, admin_user):
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('purchase_requests', 'purchase_orders', 'receiving_reports', 'products'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    clear_module_config_cache()
    db_session.commit()
    yield
    clear_module_config_cache()


@pytest.fixture
def company_defaults(db_session):
    """The company-wide setting these used to print from."""
    for slot, name in ((1, 'ANGILYN MALAPASCUA'), (2, 'DON CHI'), (3, 'ALFREDO REDULFIN JR.')):
        AppSettings.set_setting('pr_sig%d_name' % slot, name)
    for slot, name in ((1, 'RR PREPARER'), (2, 'RR CHECKER'), (3, 'RR RECEIVER')):
        AppSettings.set_setting('rr_sig%d_name' % slot, name)
    db_session.commit()


def _login(client, admin_user, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': admin_user.username, 'password': 'admin123'},
                follow_redirects=True)


# ------------------------------------------------------------- the form
def test_the_pr_form_offers_the_three_signatory_inputs(client, db_session,
                                                       admin_user, main_branch):
    _login(client, admin_user, main_branch)
    resp = client.get('/purchase-requests/create')
    assert resp.status_code == 200
    for name in (b'name="prepared_by"', b'name="noted_by"', b'name="approved_by"'):
        assert name in resp.data, '%s is not rendered, so it can never be filled in' % name


def test_the_rr_form_offers_its_own_three(client, db_session, admin_user, main_branch):
    """RR's roles are Prepared / Checked / RECEIVED -- not the PO's Approved."""
    _login(client, admin_user, main_branch)
    resp = client.get('/receiving-reports/create')
    assert resp.status_code == 200
    for name in (b'name="prepared_by"', b'name="checked_by"', b'name="received_by"'):
        assert name in resp.data
    assert b'name="approved_by"' not in resp.data, \
        "RR took PO's roles instead of its own"


def test_a_new_pr_prefills_from_the_company_default(client, db_session, admin_user,
                                                    main_branch, company_defaults):
    """What keeps a configured install printing the same names on day one."""
    _login(client, admin_user, main_branch)
    resp = client.get('/purchase-requests/create')
    assert b'ANGILYN MALAPASCUA' in resp.data
    assert b'ALFREDO REDULFIN JR.' in resp.data


# ------------------------------------------------------------- the write
def _create_pr(client, number, **sig):
    import json
    data = {'pr_number': number, 'request_date': date(2026, 8, 21).isoformat(),
            'reason': 'test', 'date_needed': '',
            'line_items': json.dumps([{'description': 'COAL', 'quantity': '1'}])}
    data.update(sig)
    return client.post('/purchase-requests/create', data=data, follow_redirects=True)


def test_the_typed_names_are_stored_on_the_requisition(client, db_session, admin_user,
                                                       main_branch, company_defaults):
    _login(client, admin_user, main_branch)
    _create_pr(client, '00090', prepared_by='ONE OFF PREPARER',
               noted_by='ONE OFF NOTER', approved_by='ONE OFF APPROVER')

    pr = PurchaseRequest.query.filter_by(pr_number='00090').first()
    assert pr is not None, 'the requisition was not created'
    assert pr.prepared_by == 'ONE OFF PREPARER'
    assert pr.noted_by == 'ONE OFF NOTER'
    assert pr.approved_by == 'ONE OFF APPROVER'


def test_a_one_off_signatory_does_not_change_the_company_default(
        client, db_session, admin_user, main_branch, company_defaults):
    """The whole point of moving these onto the document."""
    _login(client, admin_user, main_branch)
    _create_pr(client, '00091', prepared_by='TEMPORARY COVER',
               noted_by='DON CHI', approved_by='ALFREDO REDULFIN JR.')

    assert AppSettings.get_setting('pr_sig1_name') == 'ANGILYN MALAPASCUA', \
        'saving a document rewrote the company-wide setting'


def test_a_blank_stays_blank(client, db_session, admin_user, main_branch, company_defaults):
    """A cleared name is a choice -- print an empty ruled line -- not missing
    data to be silently refilled from the company setting at save time."""
    _login(client, admin_user, main_branch)
    _create_pr(client, '00092', prepared_by='', noted_by='', approved_by='')

    pr = PurchaseRequest.query.filter_by(pr_number='00092').first()
    assert pr is not None
    assert pr.prepared_by is None and pr.noted_by is None and pr.approved_by is None


# ------------------------------------------------------------- the printout
def _pr_row(db_session, branch, number, **sig):
    pr = PurchaseRequest(pr_number=number, branch_id=branch.id,
                         request_date=date(2026, 8, 21), status='approved', **sig)
    db_session.add(pr)
    db_session.flush()
    pr.line_items.append(PurchaseRequestItem(purchase_request_id=pr.id, line_number=1,
                                             description='COAL', quantity=1))
    db_session.commit()
    return pr


def test_the_printout_uses_the_documents_own_names(client, db_session, admin_user,
                                                   main_branch, company_defaults):
    pr = _pr_row(db_session, main_branch, '00093', prepared_by='DOC PREPARER',
                 noted_by='DOC NOTER', approved_by='DOC APPROVER')
    _login(client, admin_user, main_branch)

    resp = client.get('/purchase-requests/%d/print' % pr.id)
    assert resp.status_code == 200
    assert b'DOC PREPARER' in resp.data
    assert b'ANGILYN MALAPASCUA' not in resp.data, \
        'the printout ignored the document and used the company setting'


def test_a_document_predating_this_feature_still_prints_the_company_names(
        client, db_session, admin_user, main_branch, company_defaults):
    """THE regression guard. Every existing requisition has NULL columns; without
    the per-slot fallback they would all print three blank lines."""
    pr = _pr_row(db_session, main_branch, '00094')      # all three NULL
    _login(client, admin_user, main_branch)

    resp = client.get('/purchase-requests/%d/print' % pr.id)
    assert resp.status_code == 200
    assert b'ANGILYN MALAPASCUA' in resp.data
    assert b'ALFREDO REDULFIN JR.' in resp.data


def test_the_fallback_is_per_slot_not_all_or_nothing(client, db_session, admin_user,
                                                     main_branch, company_defaults):
    """A document naming only its approver must not lose the other two."""
    pr = _pr_row(db_session, main_branch, '00095', approved_by='ONLY THE APPROVER')
    _login(client, admin_user, main_branch)

    resp = client.get('/purchase-requests/%d/print' % pr.id)
    assert b'ONLY THE APPROVER' in resp.data
    assert b'ANGILYN MALAPASCUA' in resp.data, \
        'a document that set one slot lost the company default on the others'


# ------------------------------------------------- the SAME rules for RR
def _rr_row(db_session, branch, number, vendor, **sig):
    from app.receiving_reports.models import ReceivingReport
    rr = ReceivingReport(rr_number=number, branch_id=branch.id,
                         receipt_date=date(2026, 8, 21),
                         vendor_id=vendor.id, vendor_name=vendor.name,
                         status='draft', **sig)
    db_session.add(rr)
    db_session.commit()
    return rr


@pytest.fixture
def rr_vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='SIGV1', name='Signatory Vendor',
               check_payee_name='Signatory Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def test_the_rr_printout_uses_the_documents_own_names(
        client, db_session, admin_user, main_branch, rr_vendor, company_defaults):
    """RR gets the same treatment as PR -- asserted separately rather than
    assumed from the shared helper, because each document wires its own view."""
    rr = _rr_row(db_session, main_branch, 'RR-0001', rr_vendor,
                 prepared_by='RR DOC PREPARER', checked_by='RR DOC CHECKER',
                 received_by='RR DOC RECEIVER')
    _login(client, admin_user, main_branch)

    resp = client.get('/receiving-reports/%d/print' % rr.id)
    assert resp.status_code == 200
    assert b'RR DOC RECEIVER' in resp.data
    assert b'RR RECEIVER' not in resp.data.replace(b'RR DOC RECEIVER', b''), \
        'the RR printout used the company setting instead of the document'


def test_an_rr_predating_this_feature_still_prints_the_company_names(
        client, db_session, admin_user, main_branch, rr_vendor, company_defaults):
    rr = _rr_row(db_session, main_branch, 'RR-0002', rr_vendor)   # all NULL
    _login(client, admin_user, main_branch)

    resp = client.get('/receiving-reports/%d/print' % rr.id)
    assert resp.status_code == 200
    assert b'RR PREPARER' in resp.data and b'RR RECEIVER' in resp.data


def test_the_date_needed_hint_is_gone(client, db_session, admin_user, main_branch):
    """Owner directive 2026-08-21: the explanatory paragraph under Date Needed
    was removed from the requisition form.

    The BEHAVIOUR it described is unchanged and still guarded elsewhere --
    _assign_date_needed() clears the date when ASAP is ticked, and a blank Date
    Needed still prints blank rather than ASAP. Only the on-screen text went.
    """
    _login(client, admin_user, main_branch)
    resp = client.get('/purchase-requests/create')
    assert resp.status_code == 200
    assert b'name="date_needed"' in resp.data, \
        'anti-vacuity: the Date Needed field itself is gone, not just its hint'
    assert b'if the goods are wanted immediately' not in resp.data
