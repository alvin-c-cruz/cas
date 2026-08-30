"""A REFUSED Purchase Requisition save must hand back the requester's lines.

BUG-PR-CREATE-DROPS-LINES-ON-REJECT. The third instance of one defect.

2026-08-05 fixed it in Sales Orders and swept `sales_invoices`,
`delivery_receipts`, `accounts_payable`, `quotations` -- the sales-side FAMILY.
Nobody ran `grep -rn "line_items=\\[\\]" app/`. purchase_orders already carried
four such sites that day; twenty-five days later it deterministically blocked
PhilGen's purchaser, who reported it in her own words. That fix (2026-08-30,
b36b8dfd) then listed purchase_requests as "not yet checked" -- and it was wrong
in both directions: purchase_requests had three sites nobody had ever
enumerated, in the FIRST step of the very PR -> PO -> RR chain the affected user
runs.

Why this one had not bitten yet: `generate_pr_number()` still uses the global
max, so its suggestion cannot collide. That is the same accident that protected
purchase_orders until 7a5c5018 replaced its numbering with a per-purchaser pad.
The defect was always there; the trigger simply had not arrived.

RENDER assertions: the bug is what the redisplayed FORM carries. A test that
only checked "no requisition was created" passes while every line is dropped.
"""
import json
from datetime import date

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]

LINE_DESC = 'PORTLAND CEMENT 40KG'
SECOND_DESC = 'REBAR 6M X 8MM'


@pytest.fixture(autouse=True)
def _modules_on(db_session):
    for key in ('products', 'purchase_requests'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _lines(*descriptions, uom_id=None):
    out = []
    for d in descriptions:
        row = {'description': d, 'quantity': '50'}
        if uom_id is not None:
            row['uom_id'] = uom_id
        out.append(row)
    return json.dumps(out)


def _form(pr_number, lines, **over):
    data = {'pr_number': pr_number, 'request_date': '2026-08-30',
            'reason': '', 'line_items': lines}
    data.update(over)
    return data


def _existing(body):
    """The line array the form hands its row renderer."""
    import re
    m = re.search(r'const EXISTING = (\[.*?\]);', body, re.S)
    assert m, 'the PR form no longer embeds its line items as EXISTING'
    return json.loads(m.group(1))


class TestARefusedSaveGivesTheLinesBack:

    def test_a_duplicate_number_does_not_cost_the_requester_her_lines(
            self, client, db_session, admin_user, main_branch):
        db.session.add(PurchaseRequest(pr_number='PR-DUP', branch_id=main_branch.id,
                                       request_date=date(2026, 8, 30),
                                       status='draft', created_by_id=admin_user.id))
        db.session.commit()
        _login(client, admin_user, main_branch)

        resp = client.post('/purchase-requests/create',
                           data=_form('PR-DUP', _lines(LINE_DESC)))

        body = resp.data.decode()
        assert 'Purchase Requisition number already exists.' in body, \
            'the duplicate was not refused -- this no longer exercises the reject path'
        assert LINE_DESC in body, 'the refused save discarded the requested items'

    def test_every_line_comes_back_not_merely_the_first(
            self, client, db_session, admin_user, main_branch):
        db.session.add(PurchaseRequest(pr_number='PR-DUP', branch_id=main_branch.id,
                                       request_date=date(2026, 8, 30),
                                       status='draft', created_by_id=admin_user.id))
        db.session.commit()
        _login(client, admin_user, main_branch)

        body = client.post('/purchase-requests/create',
                           data=_form('PR-DUP', _lines(LINE_DESC, SECOND_DESC))).data.decode()

        assert LINE_DESC in body and SECOND_DESC in body, \
            'not every line survived the refused save'

    def test_a_wtforms_validation_failure_also_gives_the_lines_back(
            self, client, db_session, admin_user, main_branch):
        """The commonest refusal of all -- a required header field left blank --
        never reaches the explicit rejection above. It falls through to the
        function's final render, which serves the fresh GET and the failed POST
        from the same hardcoded empty list."""
        _login(client, admin_user, main_branch)

        body = client.post('/purchase-requests/create',
                           data=_form('', _lines(LINE_DESC))).data.decode()

        assert LINE_DESC in body, 'a plain validation failure discarded the lines'


class TestTheRestoredLineKeepsItsUnit:
    """Identical key mismatch to the one found in the browser on purchase_orders:
    the form posts `uom_id` (form.html:377) while the row renderer reads
    `d.unit_of_measure_id` (form.html:280). A naive port of the PO fix that
    restored the payload verbatim would hand every line back with an EMPTY unit
    -- products and quantities kept, every UoM re-picked by hand.
    """

    def test_the_unit_survives_a_refused_save(
            self, client, db_session, admin_user, main_branch):
        db.session.add(PurchaseRequest(pr_number='PR-DUP', branch_id=main_branch.id,
                                       request_date=date(2026, 8, 30),
                                       status='draft', created_by_id=admin_user.id))
        db.session.commit()
        _login(client, admin_user, main_branch)

        body = client.post('/purchase-requests/create',
                           data=_form('PR-DUP', _lines(LINE_DESC, uom_id=7))).data.decode()

        restored = _existing(body)
        assert len(restored) == 1, 'the line did not come back at all'
        assert restored[0].get('unit_of_measure_id') == 7, (
            'the restored line lost its unit -- the renderer reads '
            'unit_of_measure_id and the POST spells it uom_id')

    def test_a_free_text_unit_is_not_given_a_bogus_id(
            self, client, db_session, admin_user, main_branch):
        """CONTROL. A line with no UoM master id must not be handed one."""
        db.session.add(PurchaseRequest(pr_number='PR-DUP', branch_id=main_branch.id,
                                       request_date=date(2026, 8, 30),
                                       status='draft', created_by_id=admin_user.id))
        db.session.commit()
        _login(client, admin_user, main_branch)

        body = client.post('/purchase-requests/create',
                           data=_form('PR-DUP', _lines(LINE_DESC, uom_id=None))).data.decode()

        assert _existing(body)[0].get('unit_of_measure_id') is None, \
            'a line with no unit was handed a fabricated master id'


class TestTheControls:

    def test_a_fresh_create_form_is_still_empty(
            self, client, db_session, admin_user, main_branch):
        """CONTROL. The final render serves BOTH the failed POST and the fresh
        GET; restoring unconditionally would pre-fill a brand-new requisition
        with the previous request's lines."""
        _login(client, admin_user, main_branch)

        body = client.get('/purchase-requests/create').data.decode()

        assert LINE_DESC not in body and SECOND_DESC not in body, \
            'a brand-new PR form arrived with line items already on it'

    def test_a_refused_save_still_creates_nothing(
            self, client, db_session, admin_user, main_branch):
        """CONTROL. Handing the lines back must not let the requisition through."""
        db.session.add(PurchaseRequest(pr_number='PR-DUP', branch_id=main_branch.id,
                                       request_date=date(2026, 8, 30),
                                       status='draft', created_by_id=admin_user.id))
        db.session.commit()
        _login(client, admin_user, main_branch)

        client.post('/purchase-requests/create', data=_form('PR-DUP', _lines(LINE_DESC)))

        assert PurchaseRequest.query.filter_by(pr_number='PR-DUP').count() == 1, \
            'the refused save created a SECOND requisition on the duplicate number'

    def test_a_good_save_still_works(
            self, client, db_session, admin_user, main_branch):
        """CONTROL. The happy path is untouched -- and the one that caught the
        shadowed-builtin break when this fix was ported to Sales Orders."""
        _login(client, admin_user, main_branch)

        client.post('/purchase-requests/create',
                    data=_form('PR-OK-1', _lines(LINE_DESC)), follow_redirects=True)

        pr = PurchaseRequest.query.filter_by(pr_number='PR-OK-1').first()
        assert pr is not None, 'a valid Purchase Requisition no longer saves'
        assert [li.description for li in pr.line_items] == [LINE_DESC]
