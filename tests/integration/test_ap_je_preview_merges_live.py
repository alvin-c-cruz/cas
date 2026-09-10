"""The AP form's LIVE journal-entry preview sums legs on the same account.

Owner, 2026-09-10: "the sum up only occurs after clicking the SAVE button. upon
adding a new line with the same account the JE show multiple similar accounts."

There are THREE journal-entry surfaces in this app and they are built by three
different pieces of code:

  1. the printed face      -- server, from the stored ORM lines
  2. the detail page       -- server, from dict rows (so it can preview a draft)
  3. THIS one              -- the browser, rebuilt on every keystroke

Fixing the two server surfaces left this one showing the account title once per
line until the page was saved and re-rendered, which is exactly the "weird"
behaviour reported: the same voucher summed after save and not before.

The JS is EXECUTED here rather than pattern-matched. A source assertion would
have passed against the broken version too -- the rows were always pushed, just
never merged. node is required, never skipped: a test that skips when its
runtime is missing observes nothing and turns the suite green for the wrong
reason.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]

FORM = pathlib.Path('app/accounts_payable/templates/accounts_payable/form.html')

HARNESS = r"""
// Minimal shim: renderJEPreview only touches three elements and writes innerHTML.
const captured = {};
function el(id) {
  return { set innerHTML(v) { captured[id] = v; }, get innerHTML() { return captured[id] || ''; },
           style: {}, classList: { add(){}, remove(){}, toggle(){} } };
}
const _els = {};
global.document = {
  getElementById: (id) => (_els[id] = _els[id] || el(id)),
  querySelector: () => null, querySelectorAll: () => [],
};
global.window = global;

const data = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
global.lineItems     = data.lineItems;
global.allAccounts   = data.allAccounts;
global.vatCategories = data.vatCategories;
global.glAccounts    = data.glAccounts;
global.fmt = (n) => Number(n || 0).toFixed(2);
// Declared at template scope (form.html:386) and recomputed by the totals pass;
// the preview reads it for the VAT-override adjustment. These cases carry no
// VAT, so 0 is the faithful value.
global.autoVat = data.autoVat || 0;
// Loaded from static/transaction-utils.js on the real page.
global.escHtml = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;');
// The page's own number formatter (form.html). Reproduced rather than stubbed
// to nothing, so the assertions below read the same strings a user sees.
global.fmtNum = (n) => Number(n || 0).toLocaleString('en-US',
                          { minimumFractionDigits: 2, maximumFractionDigits: 2 });

eval(require('fs').readFileSync(process.argv[2], 'utf8'));

renderJEPreview(data.subtotal, data.vatUsed, data.wtUsed);
process.stdout.write(JSON.stringify({ body: captured['jePreviewBody'] || '',
                                      foot: captured['jePreviewFoot'] || '' }));
"""


def _render_preview(line_items):
    """Run the form's real renderJEPreview over these line items."""
    node = shutil.which('node')
    assert node, 'node is required for this test; it is never skipped'

    src = FORM.read_text(encoding='utf-8')
    start = src.index('function renderJEPreview(')
    # Brace-match to the function's own closing brace. Slicing to the end of the
    # <script> block instead sweeps in the template's Jinja tags ({% else %}),
    # which node cannot parse -- the first draft of this test did exactly that.
    depth, i = 0, src.index('{', start)
    while True:
        ch = src[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    js = src[start:i + 1]
    assert '{%' not in js, 'template syntax leaked into the extracted JS'

    data = {
        'lineItems': line_items,
        'allAccounts': [{'id': 1, 'code': '651004', 'name': 'MO - REPAIRS AND MAINTENANCE'},
                        {'id': 2, 'code': '652001', 'name': 'SUPPLIES'}],
        'vatCategories': [],
        'glAccounts': {'ap': {'id': 9, 'code': '211001', 'name': 'ACCOUNTS PAYABLE - TRADE'},
                       'wt': {'id': 8, 'code': '20301', 'name': 'WITHHOLDING TAX PAYABLE'}},
        'subtotal': sum(i['amount'] for i in line_items),
        'vatUsed': 0, 'wtUsed': 0, 'autoVat': 0,
    }
    with tempfile.TemporaryDirectory() as d:
        jsf = pathlib.Path(d, 'preview.js'); jsf.write_text(js, encoding='utf-8')
        dataf = pathlib.Path(d, 'data.json'); dataf.write_text(json.dumps(data), encoding='utf-8')
        harness = pathlib.Path(d, 'harness.js'); harness.write_text(HARNESS, encoding='utf-8')
        out = subprocess.run([node, str(harness), str(jsf), str(dataf)],
                             capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, 'node failed:\n%s' % (out.stderr[-1500:])
    return json.loads(out.stdout)['body']


class TestTheLivePreview:

    def test_two_lines_on_one_account_render_a_single_row(self):
        """The reported case, before saving anything."""
        body = _render_preview([
            {'account_id': 1, 'amount': 375.00, 'vat_category': None},
            {'account_id': 1, 'amount': 446.43, 'vat_category': None},
        ])
        assert body.count('651004') == 1, body
        # And it carries the SUM, not the first line's value.
        assert '821.43' in body, body

    def test_a_second_account_is_not_swallowed(self):
        """Control: merging keys on the account, it does not collapse everything."""
        body = _render_preview([
            {'account_id': 1, 'amount': 375.00, 'vat_category': None},
            {'account_id': 2, 'amount': 100.00, 'vat_category': None},
        ])
        assert body.count('651004') == 1, body
        assert body.count('652001') == 1, body

    def test_lines_with_no_account_produce_no_expense_row(self):
        """An unassigned line is skipped entirely (`if (!item.account_id) return`),
        so merging can never see two of them and mistake them for one account.

        Asserted on the EXPENSE rows only: the credit side legitimately shows
        30.00, because the payable is the subtotal of both lines. An earlier
        draft of this test asserted '30.00' not in body and failed against
        correct behaviour -- the number was the AP credit row, not a merge.
        """
        body = _render_preview([
            {'account_id': None, 'amount': 10.00, 'vat_category': None},
            {'account_id': None, 'amount': 20.00, 'vat_category': None},
        ])
        assert '651004' not in body, body
        assert '652001' not in body, body
        # Control: the payable row still rendered, so the page is not blank.
        assert '211001' in body, body
