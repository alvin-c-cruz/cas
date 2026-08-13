"""Execute a document form's real line-identity JS and read what it would POST.

Extracted from tests/integration/test_po_amend_ui.py (slice 2) when Purchase
Request became the second consumer. Kept in ONE place deliberately: the same
slice's whole-branch review filed `m4` -- "a fix to one copy will not reach the
other" -- against the duplicated validator, and that duplication then cost a
separate change to close the identical defects on the Sales Order side. A
120-line DOM shim copied per document is the same bet.

WHY THIS EXISTS AT ALL

Every other assertion about the identity chain is a SOURCE-SHAPE assertion: it
proves a string is present in the response, not that a browser round-trips the
line identity. That gap is not theoretical -- an adversarial review mutated the
PO dataset guard to `if (poItemId != null && d.id != null)`, which leaves every
source token intact, and all the text-level tests stayed green while every
existing line began posting as a NEW line on the second submit.

So the chain is EXECUTED. The form's real <script> block is lifted out of the
real rendered response and run in node against a minimal DOM shim; the caller
then reads what the submit handler actually serialised into the hidden input.

What this buys and what it does not:
  * BUYS: the id-fallback -> the addRow guard -> tr.dataset -> the submit
    serialiser -> the hidden input, executed as written, against the payload
    shapes the app really renders. Any rewrite of the guard, the fallback, the
    dataset key, the serialised key or the target element id changes the OUTPUT.
  * DOES NOT BUY: real DOM semantics. The shim's cells return empty values, so
    only the line IDENTITY is observed -- not quantities, VAT lookup, Choices.js,
    event wiring or native form validation. Those still need the pre-merge
    /ui-test browser pass.

node is REQUIRED, never skipped: a test that quietly skips when its runtime is
missing observes nothing and turns the suite green for the wrong reason. Same
rule tests/integration/test_po_rev0_backfill.py states for its subprocesses.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

_JS_DRIVER = r'''
'use strict';
// Minimal DOM shim: enough for a CAS document form's line JS, nothing more.
// argv[2] = file holding the form's extracted <script> body
// argv[3] = the id of the hidden input the serialiser is EXPECTED to write
// argv[4] = number of hand-added rows to click in via the "+ Add line" handler
// argv[5] = the form element's id (its submit handler is what we fire)
// argv[6] = the add-line button's element id
const fs = require('fs');
const vm = require('vm');

// The form's inline script calls helpers that the page loads from
// static/transaction-utils.js (escHtml, amtFmt...). Load the REAL file rather
// than restating them here: a shim copy silently diverges from the browser, and
// the whole point of this harness is to execute what the browser executes.
// argv[7] = path to transaction-utils.js
const utilsSrc = process.argv[7] ? fs.readFileSync(process.argv[7], 'utf8') : '';
const src = [utilsSrc, fs.readFileSync(process.argv[2], 'utf8')].join(';\n');
const hiddenId = process.argv[3];
const handAdded = parseInt(process.argv[4] || '0', 10);
const formId = process.argv[5];
const addBtnId = process.argv[6];

const rows = [];
const byId = {};
const handlers = {};

function cell() { return { value: '', textContent: '0', selectedOptions: [] }; }

function element(id) {
  if (!byId[id]) {
    byId[id] = {
      id: id,
      value: '',
      addEventListener: function (ev, fn) { handlers[id + ':' + ev] = fn; },
      appendChild: function (tr) { rows.push(tr); }
    };
  }
  return byId[id];
}

const document = {
  createElement: function () {
    return {
      // A real DOMStringMap coerces every value to a string; so does this, or the
      // test would see 1 where a browser sees "1".
      dataset: new Proxy({}, {
        set: function (t, k, v) { t[k] = String(v); return true; }
      }),
      innerHTML: '',
      querySelector: function () { return cell(); },
      remove: function () {}
    };
  },
  getElementById: element,
  querySelectorAll: function () { return rows; },
  addEventListener: function () {}
};

vm.runInNewContext(src, { document: document, console: console });

for (let i = 0; i < handAdded; i++) {
  const add = handlers[addBtnId + ':click'];
  if (!add) { console.error('the form never wired the add-line button ' + addBtnId); process.exit(3); }
  add({});
}

const submit = handlers[formId + ':submit'];
if (!submit) { console.error('the form never registered a submit handler on ' + formId); process.exit(2); }
submit({});
process.stdout.write(JSON.stringify({ rows: rows.length, posted: element(hiddenId).value }));
'''


def node_or_fail(marker):
    exe = shutil.which('node')
    if exe is None:
        pytest.fail(
            'node is not on PATH. This test EXECUTES a document form\'s '
            'line-identity JS -- the only layer in the suite that can observe a '
            f'rewritten guard (see this module\'s docstring; marker={marker}). It '
            'fails rather than skips on purpose: a silent skip here would make '
            'the suite green while the identity chain is broken. Install node, or '
            'delete this test deliberately and say so.')
    return exe


_LINE_ITEMS_INPUT_RE = re.compile(r'<input[^>]*name="line_items"[^>]*>')


def line_items_input(html):
    m = _LINE_ITEMS_INPUT_RE.search(html)
    assert m is not None, 'the line_items hidden input is no longer rendered'
    return m.group(0)


def line_items_input_id(html):
    tag = line_items_input(html)
    m = re.search(r'id="([^"]+)"', tag)
    assert m is not None, (
        f'the line_items hidden input carries no id: {tag} -- the submit handler '
        'reaches it with getElementById, so without an id nothing can be written '
        'to it and the form posts its static value="[]"')
    return m.group(1)


def form_script(html, marker):
    """The form's own <script> body, lifted out of the real rendered page.

    *marker* is the identity-mapping function name the script must define, e.g.
    'poItemIdOf'. Matching on it rather than on script order means the harness
    fails loudly when the mapping is deleted or moved to a static asset, instead
    of silently running the wrong block.
    """
    for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        if marker in m.group(1):
            return m.group(1)
    raise AssertionError(
        f'the form no longer emits a script defining {marker} -- the line '
        'identity mapping is gone, or it moved to a static asset (in which case '
        'this harness must be pointed at that file instead of silently passing)')


def serialise_lines(tmp_path, html, *, marker, form_id,
                    add_button_id='addLineBtn', hand_added=0):
    """Run the form's real JS and return the line array its submit handler posts.

    The hidden input's id is read out of the RENDERED HTML and handed to the
    driver, so a JS handle that no longer matches the input it is meant to fill
    (a rename on one side only) produces an empty write and fails here.
    """
    script = tmp_path / f'{form_id}_form.js'
    script.write_text(form_script(html, marker), encoding='utf-8')
    driver = tmp_path / 'driver.js'
    driver.write_text(_JS_DRIVER, encoding='utf-8')

    # Real file, resolved from this test module -- not a copy. If it moves, the
    # driver fails loudly rather than running against a stale duplicate.
    utils = (pathlib.Path(__file__).resolve().parents[2]
             / 'app' / 'static' / 'transaction-utils.js')
    assert utils.is_file(), f'transaction-utils.js not found at {utils}'

    proc = subprocess.run(
        [node_or_fail(marker), str(driver), str(script), line_items_input_id(html),
         str(hand_added), form_id, add_button_id, str(utils)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f'executing the {form_id} JS failed (exit {proc.returncode}).\n'
        f'stdout: {proc.stdout}\nstderr: {proc.stderr}')

    out = json.loads(proc.stdout)
    assert out['posted'], (
        'the submit handler wrote nothing into the hidden input '
        f'id="{line_items_input_id(html)}" -- the JS and the rendered input no '
        'longer name the same element, so a real browser posts the static '
        'value="[]" and the document is emptied to zero lines')
    return json.loads(out['posted'])
