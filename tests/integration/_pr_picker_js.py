"""Execute the Purchase Order form's REAL requisition-picker handler.

Sibling of _line_identity_js.py, and deliberately a SECOND harness rather than an
extension of that one. The picker lives in its own <script> block precisely
because it throws inside that harness's shim (see the Jinja comment above it in
purchase_orders/form.html), and the two ask different questions:

  * _line_identity_js  -- does a row keep its identity across a round-trip?
  * this one           -- what does the pull button DO to the grid?

WHY IT HAS TO EXECUTE

Everything the pull handler decides is invisible to a source-shape assertion.
"Does re-pulling a requisition line stack a second row or update the one already
there?" and "is the seeded blank row consumed when lines are pulled in?" are
answers, not strings; a render test that greps for a function name goes green
against a body that returns immediately.

WHAT IS REAL AND WHAT IS NOT

Both of the form's script blocks are lifted out of the REAL rendered response and
run together, over the real transaction-utils.js -- so addRow, recalcRow,
recalcTotals, the blank-row seeding on load and the submit serialiser are the
app's own code, and the observation point is the hidden input a browser would
POST. Not real: Choices.js (initSearchSelect is absent, which the form already
guards for), fetch (the picker's LOAD half is never fired -- the rows it would
have rendered are supplied directly), and DOM parsing. Nothing parses innerHTML,
so a cell only holds what JS assigned to it after the row was built; the pulled
rows' identity lives on tr.dataset, which IS assigned, so the payload is exact
for every dataset-carried field and empty for values that only ever existed as
markup. Quantities and prices still need the pre-merge /ui-test browser pass.

node is REQUIRED, never skipped -- same rule, same reason, as _line_identity_js.
"""
import json
import pathlib
import subprocess

from tests.integration import _line_identity_js as _js

_DRIVER = r'''
'use strict';
// argv[2] transaction-utils.js   argv[3] upper block   argv[4] picker block
// argv[5] scenario json          argv[6] hidden-input id
const fs = require('fs');
const vm = require('vm');

const scenario = JSON.parse(fs.readFileSync(process.argv[5], 'utf8'));
const hiddenId = process.argv[6];

const grid = [];          // the #lineItemsBody rows, in order
const byId = {};
const handlers = {};

function makeCell() { return { value: '', textContent: '', selectedOptions: [] }; }

// Cells are MEMOISED per selector so a write sticks -- a fresh stub per lookup
// would silently swallow the merge branch's `cell.value = ...`, which is the
// very thing under test.
function makeRow() {
  const cells = {};
  const row = {
    dataset: new Proxy({}, {
      set: function (t, k, v) { t[k] = String(v); return true; }
    }),
    innerHTML: '',
    querySelector: function (sel) {
      if (!cells[sel]) cells[sel] = makeCell();
      return cells[sel];
    },
    remove: function () {
      const i = grid.indexOf(row);
      if (i >= 0) grid.splice(i, 1);
    }
  };
  return row;
}

function element(id) {
  if (!byId[id]) {
    byId[id] = {
      id: id, value: '', textContent: '', innerHTML: '', style: {},
      _rows: [],
      addEventListener: function (ev, fn) { handlers[id + ':' + ev] = fn; },
      appendChild: function (tr) { grid.push(tr); },
      querySelectorAll: function () { return byId[id]._rows; },
      querySelector: function () { return makeCell(); }
    };
  }
  return byId[id];
}

const document = {
  createElement: makeRow,
  getElementById: element,
  querySelectorAll: function (sel) {
    if (sel === '#lineItemsBody tr') return grid.slice();
    return [];
  },
  querySelector: function (sel) {
    const m = /^#lineItemsBody tr\[data-source-pr-item-id="(.*)"\]$/.exec(sel);
    if (m) {
      return grid.filter(function (r) {
        return r.dataset.sourcePrItemId === m[1];
      })[0] || null;
    }
    return null;
  },
  addEventListener: function () {}
};

const src = [fs.readFileSync(process.argv[2], 'utf8'),
             fs.readFileSync(process.argv[3], 'utf8'),
             fs.readFileSync(process.argv[4], 'utf8')].join(';\n');
vm.runInNewContext(src, { document: document, console: console, JSON: JSON,
                          Array: Array, Number: Number, Math: Math,
                          parseFloat: parseFloat, parseInt: parseInt,
                          isFinite: isFinite, String: String, Proxy: Proxy,
                          fetch: function () { throw new Error('unused'); } });

const seeded = grid.length;   // rows the form put there on load, before any pull

// Typing into a seeded row, before any pull. The control for "a blank row is
// consumed" needs a NON-blank one to prove the rule is about blankness and not
// about position.
(scenario.edits || []).forEach(function (e) {
  grid[e.row].querySelector(e.selector).value = e.value;
});

// A session is one open-the-modal, tick some lines, press Add. Two sessions is
// how a user re-pulls -- the modal cannot show one requisition line twice.
const body = element('prPickerBody');
const add = handlers['prPickerAdd:click'];
if (!add) { console.error('the form never wired the pull-picker Add button'); process.exit(2); }

(scenario.sessions || []).forEach(function (session) {
  body._rows = session.map(function (pick) {
    return {
      dataset: { row: JSON.stringify(pick.row) },
      querySelector: function (sel) {
        if (sel === '.pr-pick') return { checked: pick.checked !== false };
        if (sel === '.pr-pick-qty') return { value: String(pick.qty) };
        return null;
      }
    };
  });
  add({});
});

// Read what a browser would actually POST.
const submit = handlers['poForm:submit'];
if (!submit) { console.error('the form never registered its submit handler'); process.exit(3); }
submit({});

process.stdout.write(JSON.stringify({
  seeded: seeded, rows: grid.length, posted: element(hiddenId).value
}));
'''


def pull_and_serialise(tmp_path, html, sessions, edits=None):
    """Drive the pull picker over *sessions* and return the POSTed line array.

    *sessions* is a list of pull sessions; each is a list of
    ``{'row': <an open_lines_for_branch row dict>, 'qty': '20'}`` picks, i.e.
    exactly what /purchase-requests/open-lines would have rendered into the modal
    with the tick box on.

    *edits* optionally types into the rows the form seeded on load, as
    ``{'row': 0, 'selector': '.po-desc', 'value': 'typed'}``, before any pull.

    Returns ``(seeded_row_count, posted_lines)`` -- the first is how many rows the
    form put in the grid on LOAD, before any pull, so a test can prove the blank
    row was really there to be consumed rather than never seeded.
    """
    upper = tmp_path / 'po_upper.js'
    upper.write_text(_js.form_script(html, 'poItemIdOf'), encoding='utf-8')
    picker = tmp_path / 'po_picker.js'
    picker.write_text(_js.form_script(html, 'prPickerAdd'), encoding='utf-8')
    driver = tmp_path / 'picker_driver.js'
    driver.write_text(_DRIVER, encoding='utf-8')
    cfg = tmp_path / 'scenario.json'
    cfg.write_text(json.dumps({'sessions': sessions, 'edits': edits or []}),
                   encoding='utf-8')

    utils = (pathlib.Path(__file__).resolve().parents[2]
             / 'app' / 'static' / 'transaction-utils.js')
    assert utils.is_file(), f'transaction-utils.js not found at {utils}'

    proc = subprocess.run(
        [_js.node_or_fail('prPickerAdd'), str(driver), str(utils), str(upper),
         str(picker), str(cfg), _js.line_items_input_id(html)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f'executing the pull-picker JS failed (exit {proc.returncode}).\n'
        f'stdout: {proc.stdout}\nstderr: {proc.stderr}')

    out = json.loads(proc.stdout)
    assert out['posted'], 'the submit handler wrote nothing into the hidden input'
    return out['seeded'], json.loads(out['posted'])
