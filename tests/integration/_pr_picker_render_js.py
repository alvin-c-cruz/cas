"""Execute the requisition picker's LOAD half and return the markup it emits.

A THIRD harness, and deliberately not an extension of _pr_picker_js. That one
stubs `fetch` to throw and supplies picked rows directly, because it asks what
the pull button does to the GRID. This one asks the opposite question -- what
the picker DRAWS when the fetch comes back -- so it has to fire the half the
other harness suppresses.

WHY IT HAS TO EXECUTE

The status chip exists to be looked at. Its whole content is decided inside the
`rows.map(...)` template literal: which statuses get a chip, what the chip says,
and what it is titled. A test that greps the rendered page for `pr_status` goes
green against a row template that reads the field and throws it away, which is
precisely the failure mode worth catching here.

WHAT IS REAL AND WHAT IS NOT

Real: the form's own picker <script>, lifted out of the live rendered response,
and the markup string it assigns to #prPickerBody. Not real: the DOM (nothing
parses the emitted HTML -- assertions are made against the string), Choices.js,
and the network (fetch is stubbed to hand back the supplied rows). The visual
result is still the pre-merge /ui-test browser pass's job; what this pins is
that the row template emits the attributes at all.

node is REQUIRED, never skipped -- same rule, same reason, as _line_identity_js.
"""
import json
import pathlib
import subprocess

from tests.integration import _line_identity_js as _js

_DRIVER = r'''
'use strict';
// argv[2] picker block  argv[3] rows json  argv[4] upper block  argv[5] transaction-utils.js
const fs = require('fs');
const vm = require('vm');

const rows = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const byId = {};
const handlers = {};

function element(id) {
  if (!byId[id]) {
    byId[id] = {
      id: id, value: '', textContent: '', innerHTML: '', style: {}, _rows: [],
      addEventListener: function (ev, fn) { handlers[id + ':' + ev] = fn; },
      appendChild: function () {},
      querySelectorAll: function () { return byId[id]._rows; },
      querySelector: function () { return { value: '', textContent: '' }; }
    };
  }
  return byId[id];
}

const document = {
  createElement: function () {
    return { dataset: {}, innerHTML: '', style: {},
             querySelector: function () { return { value: '' }; } };
  },
  getElementById: element,
  querySelectorAll: function () { return []; },
  querySelector: function () { return null; },
  addEventListener: function () {}
};

// The picker's LOAD half, which _pr_picker_js deliberately suppresses. Resolved
// through real promises so the handler's own .then() chain is what runs.
function fetchStub() {
  return Promise.resolve({ json: function () { return Promise.resolve({lines: rows}); } });
}

// ALL THREE, joined, exactly as _pr_picker_js does. The picker calls escHtml,
// which lives in transaction-utils.js, and the form's upper block defines the
// grid helpers it hands rows to. Load the picker alone and escHtml is undefined,
// the handler's .then() throws, and its own .catch() quietly draws a "could not
// load" row -- whereupon every absence assertion passes against markup holding
// no rows at all. That is not hypothetical; it is what this harness did on its
// first run. picker_markup() now refuses that output outright.
vm.runInNewContext([fs.readFileSync(process.argv[5], 'utf8'),
                    fs.readFileSync(process.argv[4], 'utf8'),
                    fs.readFileSync(process.argv[2], 'utf8')].join(';\n'),
                   { document: document, console: console, JSON: JSON,
                     Array: Array, Number: Number, Math: Math, String: String,
                     Promise: Promise, parseFloat: parseFloat, parseInt: parseInt,
                     isFinite: isFinite, Proxy: Proxy, fetch: fetchStub });

const click = handlers['pullPrBtn:click'];
if (!click) { console.error('the form never wired the pull button'); process.exit(2); }
click();

// Let the fetch promise chain settle before reading what it drew.
setTimeout(function () {
  process.stdout.write(JSON.stringify({
    body: element('prPickerBody').innerHTML,
    emptyShown: element('prPickerEmpty').style.display !== 'none'
  }));
}, 0);
'''


def picker_markup(tmp_path, html, rows):
    """Fire the picker's fetch handler over *rows*; return what it drew.

    Returns ``{'body': <innerHTML string>, 'emptyShown': bool}``.
    """
    driver = tmp_path / 'picker_render_driver.js'
    driver.write_text(_DRIVER, encoding='utf-8')
    # Same extraction _pr_picker_js uses: the picker lives in the script block
    # that defines prPickerAdd, matched on that name rather than on script order.
    block = tmp_path / 'picker_block.js'
    block.write_text(_js.form_script(html, 'prPickerAdd'), encoding='utf-8')
    upper = tmp_path / 'upper_block.js'
    upper.write_text(_js.form_script(html, 'poItemIdOf'), encoding='utf-8')
    utils = (pathlib.Path(__file__).resolve().parents[2]
             / 'app' / 'static' / 'transaction-utils.js')
    assert utils.is_file(), f'transaction-utils.js not found at {utils}'
    rows_file = tmp_path / 'rows.json'
    rows_file.write_text(json.dumps(rows), encoding='utf-8')

    proc = subprocess.run(
        [_js.node_or_fail('the requisition picker'), str(driver), str(block),
         str(rows_file), str(upper), str(utils)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (
        f'picker render driver failed:\n{proc.stdout}\n{proc.stderr}')
    out = json.loads(proc.stdout)

    # THE VACUOUS-PASS GUARD. The picker wraps its render in .catch(), so any
    # throw inside the .then() -- a helper the harness forgot to load, a renamed
    # field -- is swallowed into a single "could not load" row. Every "no chip is
    # drawn" assertion then passes against markup containing no rows whatsoever.
    # That is not a hypothetical: it is what this harness did on its first run.
    assert 'Could not load requisitions' not in out['body'], (
        'the picker render threw and fell into its own catch() -- the markup '
        'below contains no rows, so any absence assertion over it would be '
        f'vacuous:\n{out["body"]}')
    if rows:
        assert out['body'].strip(), (
            f'rows were supplied but the picker drew nothing:\n{out!r}')
    return out
