"""Purchase Request line identity: pr_item_id through the form, and the in-place applier.

WHY PR NEEDS THIS AT ALL, AND WHY THE REASON IS NOT PO'S

PO and SO had to update lines in place because a delete-and-rebuild strands
`ReceivingReportItem.purchase_order_item_id` (and the SO delivery equivalents)
with SQLite FK enforcement off -- silent corruption, not an error.

**PR has no such child.** Nothing in the app declares a `purchase_request_item_id`;
the only downstream edge is header-level (`purchase_order_id`), and conversion
COPIES lines into a draft PO rather than pointing at them. So a rebuild here
strands nothing.

The reason is narrower and worth stating exactly: `PurchaseRequestItem.id` is what
lines two revision snapshots up row by row. `_parse_and_attach_pr_lines` appends
fresh rows, so without an in-place applier every amendment renumbers every line
and the revision history becomes uncomparable -- Rev 0 and Rev 1 would share no
row identity even for lines nobody touched.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_requests.views import _apply_amended_pr_lines

from tests.integration import _line_identity_js as _js

pytestmark = [pytest.mark.integration]

_MARKER = 'prItemIdOf'
_FORM_ID = 'prForm'


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _pr(db_session, branch, number, lines=(('Cement', '10'),), status='approved'):
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 8, 10), status=status,
                         reason='Site needs cement')
    for n, (desc, qty) in enumerate(lines, start=1):
        pr.line_items.append(PurchaseRequestItem(
            line_number=n, description=desc, quantity=Decimal(qty), uom_text='bag'))
    db_session.add(pr); db_session.commit()
    return pr


@pytest.fixture
def pr_with_higher_rowids(db_session, main_branch):
    """The PR under test, guaranteed NOT to hold the lowest line rowids.

    SQLite assigns `max(rowid)+1` PER TABLE, so on a single-row table deleting the
    only line and re-inserting hands back the SAME id -- and a delete-and-rebuild
    mutation SURVIVES an identity-stability test. Proven in slice 2, where exactly
    that test passed against a rebuilt PO. Seeding a decoy PR first pushes the real
    subject's ids above 1 so a rebuild is observable.
    """
    _pr(db_session, main_branch, 'PR-DECOY-0001', lines=(('decoy a', '1'), ('decoy b', '2')))
    return _pr(db_session, main_branch, 'PR-2026-08-0001',
               lines=(('Cement', '10'), ('Sand', '4')))


# -- the applier -------------------------------------------------------------

class TestInPlaceApplier:

    def test_ids_are_stable_when_a_line_is_edited(self, db_session, pr_with_higher_rowids):
        pr = pr_with_higher_rowids
        before = [li.id for li in pr.line_items]
        assert min(before) > 1, 'fixture precondition: ids must not start at 1'
        _apply_amended_pr_lines(pr, [
            {'pr_item_id': before[0], 'description': 'Cement', 'quantity': '25'},
            {'pr_item_id': before[1], 'description': 'Sand', 'quantity': '4'},
        ])
        db_session.commit()
        assert [li.id for li in pr.line_items] == before
        assert pr.line_items[0].quantity == Decimal('25')

    def test_a_line_absent_from_the_submission_is_removed(
            self, db_session, pr_with_higher_rowids):
        pr = pr_with_higher_rowids
        keep, drop = pr.line_items[0].id, pr.line_items[1].id
        _apply_amended_pr_lines(pr, [
            {'pr_item_id': keep, 'description': 'Cement', 'quantity': '10'}])
        db_session.commit()
        assert [li.id for li in pr.line_items] == [keep]
        assert db.session.get(PurchaseRequestItem, drop) is None

    def test_a_line_with_no_identity_is_appended_as_new(
            self, db_session, pr_with_higher_rowids):
        pr = pr_with_higher_rowids
        before = [li.id for li in pr.line_items]
        _apply_amended_pr_lines(pr, [
            {'pr_item_id': before[0], 'description': 'Cement', 'quantity': '10'},
            {'pr_item_id': before[1], 'description': 'Sand', 'quantity': '4'},
            {'pr_item_id': None, 'description': 'Gravel', 'quantity': '7'},
        ])
        db_session.commit()
        assert len(pr.line_items) == 3
        assert [li.id for li in pr.line_items][:2] == before
        assert pr.line_items[2].description == 'Gravel'

    def test_line_numbers_are_resequenced_from_one(
            self, db_session, pr_with_higher_rowids):
        pr = pr_with_higher_rowids
        second = pr.line_items[1].id
        _apply_amended_pr_lines(pr, [
            {'pr_item_id': second, 'description': 'Sand', 'quantity': '4'}])
        db_session.commit()
        assert [li.line_number for li in pr.line_items] == [1]

    def test_an_id_from_a_DIFFERENT_pr_never_resolves(
            self, db_session, main_branch, pr_with_higher_rowids):
        """SECURITY. The lookup is scoped to THIS requisition's own lines.

        A global db.session.get would let a crafted pr_item_id rewrite another
        requisition's row -- the shape slice 2's review demonstrated live on the
        PO side, where it rewrote a different order's line and emptied the target.
        """
        other = _pr(db_session, main_branch, 'PR-OTHER-0001', lines=(('Steel', '9'),))
        victim_id = other.line_items[0].id
        pr = pr_with_higher_rowids
        _apply_amended_pr_lines(pr, [
            {'pr_item_id': victim_id, 'description': 'HIJACK', 'quantity': '999'}])
        db_session.commit()
        db_session.refresh(other)
        assert other.line_items[0].description == 'Steel', 'another PR was rewritten'
        assert other.line_items[0].quantity == Decimal('9')
        # the crafted id fell through to "not found" and became a NEW line here
        assert [li.description for li in pr.line_items] == ['HIJACK']

    def test_the_applier_does_not_enforce_the_minimum_line_rule(
            self, db_session, pr_with_higher_rowids):
        """Deliberate division of responsibility, pinned so it is not "fixed".

        This function APPLIES; the amend route JUDGES the applied result with
        pr.has_requested_line(). Enforcing the rule here TOO would put it in two
        places -- the drift that let the same hole survive its first fix on the
        Purchase Order side, where one copy was closed by hand and the other left
        open behind a control test that only exercised the closed one.

        So an empty submission leaves an empty requisition IN THE SESSION, and
        the route's postcondition is what refuses it and rolls back. A future
        reader adding a `kept == 0` raise here would make the route's own C1 test
        pass for the wrong reason.
        """
        pr = pr_with_higher_rowids
        _apply_amended_pr_lines(pr, [])
        assert pr.line_items == []
        assert pr.has_requested_line() is False, (
            'the postcondition the ROUTE checks must be able to see this state')
        db_session.rollback()

    def test_a_string_id_resolves_the_same_as_an_int(
            self, db_session, pr_with_higher_rowids):
        # The browser posts strings. If the applier keyed on the raw value it
        # would miss every existing row and rebuild the whole document.
        pr = pr_with_higher_rowids
        before = [li.id for li in pr.line_items]
        _apply_amended_pr_lines(pr, [
            {'pr_item_id': str(before[0]), 'description': 'Cement', 'quantity': '11'},
            {'pr_item_id': str(before[1]), 'description': 'Sand', 'quantity': '4'},
        ])
        db_session.commit()
        assert [li.id for li in pr.line_items] == before


# -- the JS chain, EXECUTED (see tests/integration/_line_identity_js.py) ------

def _edit_get(client, pr):
    resp = client.get(f'/purchase-requests/{pr.id}/edit')
    assert resp.status_code == 200
    return resp.data.decode()


def _serialise(tmp_path, html, hand_added=0):
    return _js.serialise_lines(tmp_path, html, marker=_MARKER, form_id=_FORM_ID,
                               hand_added=hand_added)


class TestLineIdentityExecuted:
    """Source-shape assertions cannot see a rewritten guard -- slice 2 proved it
    by mutating `if (poItemId != null)` to `&& d.id != null`, leaving every token
    intact and the text-level tests green. These execute the form's real JS."""

    def test_the_first_render_posts_the_stored_line_identity(
            self, client, accountant_user, main_branch, db_session, tmp_path):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, 'PR-2026-08-0002', status='draft')
        line_id = pr.line_items[0].id
        posted = _serialise(tmp_path, _edit_get(client, pr))
        assert len(posted) == 1
        assert posted[0]['pr_item_id'] == str(line_id), (
            'the form loaded an existing line from the DB and posted it without '
            'its identity -- the applier reads that as "line removed, line added" '
            'and renumbers every row, so two revision snapshots share no identity')

    def test_a_replayed_submission_still_posts_the_identity(
            self, client, accountant_user, main_branch, db_session, tmp_path):
        """The `id ?? pr_item_id` fallback's SECOND half, executed.

        A re-render after a refusal replays the SUBMITTED payload, which carries
        `pr_item_id` and no `id`. With only the `id` half of the fallback, the
        second submit after any refusal loses every line identity. Slice 2 found
        this live on the PO form and it is the single most ordinary sequence a
        user produces: submit -> refused -> fix -> submit again.
        """
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, 'PR-2026-08-0003', status='draft')
        html = _edit_get(client, pr)
        # Replace the rendered EXISTING array with the REPLAY shape the amend
        # route will hand back on a refusal (task 4): pr_item_id, no id.
        replay = json.dumps([{'pr_item_id': str(pr.line_items[0].id),
                              'description': 'Cement', 'quantity': '10',
                              'uom_text': 'bag', 'product_id': None}])
        html = _replace_existing(html, replay)
        posted = _serialise(tmp_path, html)
        assert posted[0]['pr_item_id'] == str(pr.line_items[0].id), (
            'the replayed payload lost its identity -- only the `id` half of the '
            'fallback is wired, so every resubmit after a refusal rebuilds the '
            'whole requisition')

    def test_a_hand_added_row_posts_no_identity_while_the_existing_one_keeps_its_own(
            self, client, accountant_user, main_branch, db_session, tmp_path):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, 'PR-2026-08-0004', status='draft')
        line_id = pr.line_items[0].id
        posted = _serialise(tmp_path, _edit_get(client, pr), hand_added=1)
        assert len(posted) == 2
        assert posted[0]['pr_item_id'] == str(line_id)
        assert posted[1]['pr_item_id'] is None, (
            'a row added during the amendment must post pr_item_id null; an '
            'unconditional dataset write posts the string "null" instead, and a '
            'guard that leaks the previous row id merges two lines into one')

    def test_the_serialiser_writes_into_the_rendered_hidden_input(
            self, client, accountant_user, main_branch, db_session, tmp_path):
        # Pins the JS handle against the RENDERED id. A rename on one side only
        # leaves the form posting its static value="[]".
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, 'PR-2026-08-0005', status='draft')
        html = _edit_get(client, pr)
        assert _js.line_items_input_id(html) == 'prLinesJson'
        assert _serialise(tmp_path, html)  # non-empty write


def _replace_existing(html, new_json):
    """Swap the rendered `const EXISTING = [...]` array for another payload."""
    import re
    out, n = re.subn(r'const EXISTING = .*?;', 'const EXISTING = %s;' % new_json,
                     html, count=1, flags=re.DOTALL)
    assert n == 1, 'the form no longer renders a `const EXISTING` array'
    return out
