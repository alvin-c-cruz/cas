"""The Receiving Report form goes vendor-first: pick a VENDOR, then pull open lines
from ANY of that vendor's receivable purchase orders.

Everything here asserts on the RENDERED GET (or on JS lifted out of it), never on a
payload the test built itself. A POST-contract test structurally cannot see a field
the template failed to render -- which is exactly the state this task inherited: the
form rendered `form.vendor_id` under `id="poSelect"` and then looked that VENDOR id up
in `PO_LINES`, a map keyed by PURCHASE ORDER id. No line could ever be built, and every
POST-level test stayed green because each supplied the hidden `lines` JSON itself. See
memory `csrf-only-render-drops-hidden-fields` for the same defect class.

Every absence assertion below is paired with a positive one in the same test, because
an absence alone passes just as happily when the page fails to render at all. HTML
comments, inline <style> and inline <script> are all in the response body, so the
literals asserted absent are swept out of those too.
"""
import json
import re
import subprocess
from datetime import date
from decimal import Decimal

import pytest

from tests.integration._line_identity_js import form_script, node_or_fail

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


# -- fixtures ------------------------------------------------------------------

@pytest.fixture
def rr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def other_vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='OTH-VEND-FR', name='Other Vendor FR', tin='111-222-334-001')
    db_session.add(v); db_session.commit()
    return v


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _po(db_session, branch, vendor, number, qty=10, status='approved', description='Cement'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status=status,
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description=description,
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _draft_rr(db_session, branch, vendor, po, number='RR-FR-001', qty=Decimal('2')):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number,
                         receipt_date=date(2026, 7, 11), purchase_order_id=po.id,
                         vendor_id=vendor.id, vendor_name=vendor.name, status='draft')
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=po.line_items[0].id, received_quantity=qty))
    db_session.add(rr); db_session.commit()
    return rr


@pytest.fixture
def create_page(client, admin_user, main_branch, rr_enabled):
    _login(client, admin_user, main_branch)
    resp = client.get('/receiving-reports/create')
    assert resp.status_code == 200, f'the create form did not render: {resp.status_code}'
    return resp.data.decode()


# -- the header: a vendor picker, and no single-PO select ----------------------

class TestTheHeaderIsVendorFirst:

    def test_a_vendor_picker_is_rendered(self, create_page):
        assert 'name="vendor_id"' in create_page
        assert 'id="vendorSelect"' in create_page

    def test_the_old_single_purchase_order_select_is_gone(self, create_page):
        """ABSENCE, paired with the positive that replaced it.

        `poSelect` was the id the vendor select was still wearing, and the JS keyed
        the PO-id map by whatever it held. `purchase_order_id` is the header column
        the picker used to submit. Neither may survive anywhere in the body --
        comments and inline script included, which is why this reads the whole
        response rather than a parsed form.
        """
        assert 'poSelect' not in create_page
        assert 'purchase_order_id' not in create_page
        assert 'id="vendorSelect"' in create_page          # the positive pair

    def test_the_vendor_field_is_wrapped_for_the_choices_treatment(self, create_page):
        """Without picker-field the enhanced select renders as bare borderless text
        beside the ordinary inputs next to it (the same fix the PO form needed)."""
        assert 'picker-field' in create_page


# -- the pull control and the grid --------------------------------------------

class TestThePullControl:

    def test_a_pull_from_purchase_orders_control_is_rendered(self, create_page):
        assert 'id="pullPoBtn"' in create_page
        assert '+ Pull from Purchase Orders' in create_page

    def test_the_picker_modal_is_rendered(self, create_page):
        assert 'id="poPickerModal"' in create_page
        assert 'id="poPickerBody"' in create_page
        assert 'id="poPickerAdd"' in create_page

    def test_no_free_form_add_line_control_is_offered(self, create_page):
        """ABSENCE, paired below with the positive that a pull control IS offered.

        Every RR line references a purchase_order_item_id (NOT NULL) -- a receiver
        cannot invent one -- so an "+ Add line" button would build a row that can
        never be saved.
        """
        assert 'addLineBtn' not in create_page
        assert 'id="pullPoBtn"' in create_page             # the positive pair


class TestTheGrid:

    def test_the_grid_has_a_from_po_column_header(self, create_page):
        assert '<th>From PO</th>' in create_page

    def test_the_placeholder_no_longer_names_a_single_purchase_order(self, create_page):
        """ABSENCE, paired with the positive replacement text.

        One receipt now spans several of one vendor's orders, so "Select a Purchase
        Order to load its open lines" names a thing that no longer exists.
        """
        assert 'Select a Purchase Order to load' not in create_page
        assert 'rrGridEmptyRow' in create_page             # the positive pair
        assert 'pull the open lines' in create_page

    def test_the_hidden_lines_input_is_still_rendered(self, create_page):
        """CONTROL on the submit contract Tasks 2-3 depend on. A form that renders
        beautifully and drops this input posts value="[]" and saves nothing."""
        assert 'name="lines"' in create_page
        assert 'id="rrLinesJson"' in create_page


# -- the script blocks ---------------------------------------------------------

class TestTheScriptBlocks:

    def test_choices_and_search_select_load_before_the_inline_script(self, create_page):
        for asset in ('choices.min.js', 'transaction-utils.js', 'search-select.js'):
            assert asset in create_page, f'{asset} is not loaded'
            assert create_page.index(asset) < create_page.index('RR_LINE_INDEX'), (
                f'{asset} loads after the inline script that depends on it')

    def test_the_picker_js_is_a_separate_script_block_from_the_line_block(self, create_page):
        """The PO form splits these on purpose -- tests/integration/_line_identity_js.py
        executes a form's line block in a minimal DOM shim, and picker code (fetch,
        Choices) throws on APIs that shim does not provide. The RR line block is
        executed the same way by TestChangingTheVendorClearsTheGrid below, so the
        split is load-bearing here too, not decorative."""
        line_block = form_script(create_page, 'RR_LINE_INDEX')
        assert 'pullPoBtn' not in line_block
        assert 'fetch(' not in line_block
        assert 'initSearchSelect' not in line_block
        picker_block = form_script(create_page, 'pullPoBtn')          # the positive pair
        assert 'RR_LINE_INDEX' not in picker_block

    def test_the_vendor_picker_is_enhanced(self, create_page):
        assert 'initSearchSelect' in create_page


# -- the JSON endpoint the picker reads ---------------------------------------

class TestTheOpenLinesEndpoint:
    """GET /receiving-reports/open-lines?vendor_id=<id>[&exclude_rr_id=<id>]

    The picker cannot be purely client-side: `po_lines` is server-rendered per GET
    and is empty until a vendor is chosen, while the vendor is chosen in the browser.
    """

    def _lines(self, client, vendor_id, **args):
        qs = '&'.join([f'vendor_id={vendor_id}'] + [f'{k}={v}' for k, v in args.items()])
        resp = client.get(f'/receiving-reports/open-lines?{qs}')
        assert resp.status_code == 200, resp.status_code
        return resp.get_json()['lines']

    def test_the_chosen_vendors_open_lines_come_back_with_their_po_number(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, vl_vendor, 'PO-FR-001', qty=10)

        lines = self._lines(client, vl_vendor.id)

        assert [ln['purchase_order_item_id'] for ln in lines] == [po.line_items[0].id]
        assert lines[0]['po_number'] == 'PO-FR-001'
        assert lines[0]['po_id'] == po.id
        assert lines[0]['open'] == 10.0

    def test_another_vendors_lines_are_never_returned(
            self, client, db_session, admin_user, main_branch, vl_vendor, other_vendor,
            rr_enabled):
        _login(client, admin_user, main_branch)
        mine = _po(db_session, main_branch, vl_vendor, 'PO-FR-002')
        theirs = _po(db_session, main_branch, other_vendor, 'PO-FR-003')

        ids = [ln['purchase_order_item_id'] for ln in self._lines(client, vl_vendor.id)]

        assert mine.line_items[0].id in ids
        assert theirs.line_items[0].id not in ids

    def test_another_branchs_lines_are_never_returned(
            self, client, db_session, admin_user, main_branch, branch_manila, vl_vendor,
            rr_enabled):
        """The branch comes from the SESSION, never from the query string."""
        _login(client, admin_user, main_branch)
        here = _po(db_session, main_branch, vl_vendor, 'PO-FR-004')
        elsewhere = _po(db_session, branch_manila, vl_vendor, 'PO-FR-005')

        ids = [ln['purchase_order_item_id']
               for ln in self._lines(client, vl_vendor.id, branch_id=branch_manila.id)]

        assert here.line_items[0].id in ids
        assert elsewhere.line_items[0].id not in ids

    def test_a_fully_received_line_of_a_still_open_order_is_not_offered(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        """The order must have a SECOND, still-open line, or _eligible_purchase_orders
        drops the whole PO before this filter is ever consulted -- a one-line PO
        cannot see it, and a test built on one passes whether the filter exists or
        not."""
        from app.purchase_orders.models import PurchaseOrderItem
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, vl_vendor, 'PO-FR-006', qty=10)
        po.line_items.append(PurchaseOrderItem(
            line_number=2, description='Sand', quantity=Decimal('5'),
            unit_price=Decimal('10'), amount=Decimal('50')))
        db_session.commit()
        closed, still_open = po.line_items[0], po.line_items[1]
        rr = ReceivingReport(branch_id=main_branch.id, rr_number='RR-FR-FULL',
                             receipt_date=date(2026, 7, 11), purchase_order_id=po.id,
                             vendor_id=vl_vendor.id, vendor_name=vl_vendor.name,
                             status='approved')
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=closed.id,
            received_quantity=Decimal('10')))
        db_session.add(rr); db_session.commit()

        ids = [ln['purchase_order_item_id'] for ln in self._lines(client, vl_vendor.id)]

        assert closed.id not in ids
        assert still_open.id in ids                       # the positive pair

    def test_no_vendor_offers_nothing(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        _login(client, admin_user, main_branch)
        _po(db_session, main_branch, vl_vendor, 'PO-FR-008')

        resp = client.get('/receiving-reports/open-lines')

        assert resp.status_code == 200
        assert resp.get_json()['lines'] == []

    def test_a_viewer_cannot_read_the_picker(
            self, client, db_session, viewer_user, main_branch, vl_vendor, rr_enabled):
        """The picker carries the same role gate as the create view it feeds."""
        viewer_user.branches.append(main_branch); db_session.commit()
        _login(client, viewer_user, main_branch)
        _po(db_session, main_branch, vl_vendor, 'PO-FR-009')

        resp = client.get(f'/receiving-reports/open-lines?vendor_id={vl_vendor.id}')

        assert resp.status_code == 403

    def test_an_editor_can_read_the_picker(
            self, client, db_session, staff_user, main_branch, vl_vendor, rr_enabled):
        """CONTROL for the refusal above -- the gate is a ROLE gate, not a blanket no."""
        # The conftest staff fixture's book_permissions predate this module, and
        # per-module access is deny-by-default for staff -- without this the request
        # never reaches the role gate this test is about.
        perms = staff_user.get_book_permissions()
        perms['receiving_reports'] = True
        staff_user.set_book_permissions(perms)
        staff_user.branches.append(main_branch); db_session.commit()
        _login(client, staff_user, main_branch)
        _po(db_session, main_branch, vl_vendor, 'PO-FR-010')

        resp = client.get(f'/receiving-reports/open-lines?vendor_id={vl_vendor.id}')

        assert resp.status_code == 200
        assert len(resp.get_json()['lines']) == 1

    def test_excluding_this_receipt_reopens_the_quantity_it_holds(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        """The edit picker must not count the receipt being edited against itself."""
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, vl_vendor, 'PO-FR-011', qty=10)
        rr = ReceivingReport(branch_id=main_branch.id, rr_number='RR-FR-EXCL',
                             receipt_date=date(2026, 7, 11), purchase_order_id=po.id,
                             vendor_id=vl_vendor.id, vendor_name=vl_vendor.name,
                             status='approved')
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=po.line_items[0].id,
            received_quantity=Decimal('4')))
        db_session.add(rr); db_session.commit()

        without = self._lines(client, vl_vendor.id)
        excluded = self._lines(client, vl_vendor.id, exclude_rr_id=rr.id)

        assert without[0]['open'] == 6.0
        assert excluded[0]['open'] == 10.0


# -- the edit form pre-fills its own lines, each showing its PO ----------------

class TestTheEditFormPrefillsItsOwnLines:

    def test_an_existing_line_renders_with_the_po_number_it_came_from(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, vl_vendor, 'PO-FR-EDIT', qty=10)
        rr = _draft_rr(db_session, main_branch, vl_vendor, po, number='RR-FR-EDIT')

        body = client.get(f'/receiving-reports/{rr.id}/edit').data.decode()

        assert 'PO-FR-EDIT' in body, 'the grid cannot label a line with its order'
        marker = 'const PO_NUMBERS = '
        payload, _ = json.JSONDecoder().raw_decode(body, body.index(marker) + len(marker))
        assert payload[str(po.id)] == 'PO-FR-EDIT'
        assert str(po.line_items[0].id) in body


# -- changing the vendor: the grid is cleared, with a visible warning ----------

_VENDOR_CHANGE_DRIVER = r'''
'use strict';
// Minimal DOM shim for the RR form's LINE block -- enough to load it and fire the
// vendor picker's change handler, nothing more. Sibling in spirit to
// tests/integration/_line_identity_js.py's driver; kept here because it observes a
// different thing (grid clearing) on a form that uses a different hidden input.
// argv[2] = file holding the extracted <script> body
// argv[3] = path to the REAL transaction-utils.js (escHtml lives there)
// argv[4] = 'change' to fire the vendor change handler, anything else to just load
const fs = require('fs');
const vm = require('vm');
const src = [fs.readFileSync(process.argv[3], 'utf8'),
             fs.readFileSync(process.argv[2], 'utf8')].join(';\n');

const byId = {};
const handlers = {};
function element(id) {
  if (!byId[id]) {
    byId[id] = {
      id: id, value: '', innerHTML: '', style: {display: ''},
      addEventListener: function (ev, fn) { handlers[id + ':' + ev] = fn; },
      // Enough of a DOM to observe WHAT the grid holds. Rows are appended as HTML
      // text, so the driver reads them back the same way a reviewer would.
      insertAdjacentHTML: function (pos, html) { this.innerHTML += html; }
    };
  }
  return byId[id];
}
// Just enough of querySelector to answer the ONE question the grid asks it: "is
// there already a row for this purchase order line?" It is answered from the
// grid's own markup, so a lookup that stops finding real rows -- the mutation that
// turns a merge back into a stacked duplicate -- is observable here.
const inputs = {};
function rowStub(poi) {
  return {
    querySelector: function () {
      if (!inputs[poi]) inputs[poi] = {value: ''};
      return inputs[poi];
    }
  };
}
const document = {
  getElementById: element,
  querySelector: function (sel) {
    const m = /data-poi="([^"]+)"/.exec(sel || '');
    if (!m) return null;
    const body = byId['rrGridBody'];
    if (!body || body.innerHTML.indexOf('data-poi="' + m[1] + '"') === -1) return null;
    return rowStub(m[1]);
  },
  // The submit serialiser reads the live inputs; that contract is covered by the
  // POST-level RR suites, not here.
  querySelectorAll: function () { return []; },
  addEventListener: function () {}
};

const ctx = {document: document, console: console};
vm.runInNewContext(src, ctx);

const before = element('rrGridBody').innerHTML;
if (process.argv[4] === 'change') {
  const fn = handlers['vendorSelect:change'];
  if (!fn) { console.error('the form never wired a change handler on vendorSelect'); process.exit(2); }
  element('vendorSelect').value = '999';
  fn({});
} else if (process.argv[4] === 'repull') {
  // The picker's own path: the same purchase order line added twice.
  if (typeof ctx.rrAddLine !== 'function') {
    console.error('the line block no longer exposes rrAddLine'); process.exit(3);
  }
  const r = {purchase_order_item_id: 4242, po_number: 'PO-REPULL', product_code: 'X',
             product_name: 'Widget', uom: 'pc', ordered: 9, received: 0, open: 9};
  ctx.rrAddLine(r, '1');
  ctx.rrAddLine(r, '3');
}
process.stdout.write(JSON.stringify({
  before: before,
  after: element('rrGridBody').innerHTML,
  notice: element('rrVendorChangeNotice').style.display,
  repulled_qty: inputs['4242'] ? inputs['4242'].value : null
}));
'''


def _run_line_block(tmp_path, html, action):
    """Execute the RR form's REAL line block and report what the grid holds.

    Source-shape assertions cannot tell a wired-up vendor guard from a dead one: a
    handler that clears nothing leaves every literal in the page intact. So the block
    is run as written and the grid is read afterwards.
    """
    script = tmp_path / 'rr_line_block.js'
    script.write_text(form_script(html, 'RR_LINE_INDEX'), encoding='utf-8')
    driver = tmp_path / 'rr_driver.js'
    driver.write_text(_VENDOR_CHANGE_DRIVER, encoding='utf-8')
    import pathlib
    utils = (pathlib.Path(__file__).resolve().parents[2]
             / 'app' / 'static' / 'transaction-utils.js')
    assert utils.is_file(), f'transaction-utils.js not found at {utils}'
    proc = subprocess.run(
        [node_or_fail('RR_LINE_INDEX'), str(driver), str(script), str(utils), action],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f'executing the RR line block failed (exit {proc.returncode}).\n'
        f'stdout: {proc.stdout}\nstderr: {proc.stderr}')
    return json.loads(proc.stdout)


class TestChangingTheVendorClearsTheGrid:
    """A receipt covers ONE vendor. Lines pulled from vendor A must never survive a
    switch to vendor B -- the save would refuse them ("belongs to X"), but only after
    the receiver has typed a whole delivery in. Clearing (rather than blocking the
    switch) is what this form does, and the warning is inline HTML: confirm()/alert()
    are forbidden project-wide."""

    @pytest.fixture
    def edit_page(self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, vl_vendor, 'PO-FR-VC', qty=10)
        rr = _draft_rr(db_session, main_branch, vl_vendor, po, number='RR-FR-VC')
        return client.get(f'/receiving-reports/{rr.id}/edit').data.decode(), po

    def test_the_grid_starts_holding_the_receipts_line(self, tmp_path, edit_page):
        """CONTROL. Without this the clearing test below could pass on a grid that
        was empty all along."""
        html, po = edit_page
        out = _run_line_block(tmp_path, html, 'load')
        assert f'data-poi="{po.line_items[0].id}"' in out['before']
        assert 'rrGridEmptyRow' not in out['before'], (
            'the "no lines yet" placeholder row was not consumed by the line that '
            'landed on top of it')

    def test_changing_the_vendor_empties_the_grid(self, tmp_path, edit_page):
        html, po = edit_page
        out = _run_line_block(tmp_path, html, 'change')
        assert f'data-poi="{po.line_items[0].id}"' in out['before']
        assert 'data-poi' not in out['after']
        assert 'rrGridEmptyRow' in out['after'], 'the placeholder did not come back'

    def test_changing_the_vendor_shows_the_warning(self, tmp_path, edit_page):
        html, _ = edit_page
        loaded = _run_line_block(tmp_path, html, 'load')
        changed = _run_line_block(tmp_path, html, 'change')
        assert loaded['notice'] == 'none', 'the warning is showing before anything changed'
        assert changed['notice'] != 'none'

    def test_no_javascript_popup_is_used(self, edit_page):
        """Project rule: no confirm()/alert()/prompt(), ever."""
        html, _ = edit_page
        for banned in ('confirm(', 'alert(', 'prompt('):
            assert banned not in html, f'{banned} is forbidden -- use inline HTML'
        assert 'rrVendorChangeNotice' in html          # the positive pair


# -- one row per PO line, by construction -------------------------------------

class TestOneRowPerPurchaseOrderLine:
    """`_submitted_existing_lines()` builds a dict keyed on purchase_order_item_id, so
    two grid rows against the SAME PO line collapse to one on a bounced edit. This grid
    cannot produce two: it is rendered from RR_LINE_INDEX, which is keyed by
    purchase_order_item_id, and a re-pull MERGES into the existing row."""

    def test_the_grid_is_keyed_by_purchase_order_item_id(self, create_page):
        block = form_script(create_page, 'RR_LINE_INDEX')
        assert re.search(r'RR_LINE_INDEX\[\s*\w+\.purchase_order_item_id\s*\]', block), (
            'RR_LINE_INDEX is no longer keyed by purchase_order_item_id -- two rows '
            'for one PO line become possible, and _submitted_existing_lines silently '
            'drops one of them on a bounce')

    def test_a_re_pull_merges_into_the_existing_row(self, create_page):
        block = form_script(create_page, 'RR_LINE_INDEX')
        assert 'rrExistingRowFor' in block, (
            'nothing looks for a row already in the grid -- re-pulling a line stacks '
            'a duplicate instead of updating its quantity')

    def test_pulling_the_same_line_twice_updates_one_row(self, tmp_path, create_page):
        """EXECUTED, not asserted on source text: a merge lookup that silently stops
        finding rows leaves every literal in the page intact while every re-pull
        stacks a second row -- and two rows for one PO line are then collapsed by
        views._submitted_existing_lines(), which keys on purchase_order_item_id, so
        a bounced edit would redisplay only the second."""
        out = _run_line_block(tmp_path, create_page, 'repull')
        occurrences = out['after'].count('data-poi="4242"')
        assert occurrences == 2, (
            'one grid row emits data-poi twice (the <tr> and its quantity input), so '
            f'2 is one row -- got {occurrences}, i.e. the re-pull stacked a duplicate '
            'row instead of merging into the one already there')
        assert out['repulled_qty'] == '3', 'the re-pull did not update the quantity'

    def test_the_picker_adds_lines_through_the_merging_adder(self, create_page):
        """The picker must not hand-build a grid row: two row builders diverge, and
        the merge + placeholder-consumption rules live in rrAddLine."""
        picker = form_script(create_page, 'pullPoBtn')
        assert 'rrAddLine' in picker
        assert 'rr-recv' not in picker
