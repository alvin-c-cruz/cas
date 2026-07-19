"""Regression tests for BUG-AP-PULL-PORR-LEAVES-BLANK-LINE: pulling a PO/RR onto an AP bill
must remove the form's default blank starter line instead of leaving it orphaned as line 1
(sibling of the already-fixed BUG-SI-PULL-DR-LEAVES-BLANK-LINE)."""
import pathlib


def test_form_html_exposes_remove_blank_starter_line_helper(client, accountant_user):
    with client:
        client.post('/login', data={'username': accountant_user.username,
                                    'password': 'accountant123'}, follow_redirects=True)
        resp = client.get('/accounts-payable/create')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'window.removeBlankStarterLine' in body, (
            'form.html must expose window.removeBlankStarterLine for ap_po_billing.js to call')


def test_ap_po_billing_js_calls_remove_blank_starter_line_before_injecting():
    js_path = (pathlib.Path(__file__).resolve().parents[2]
              / 'app' / 'static' / 'ap_po_billing.js')
    text = js_path.read_text(encoding='utf-8')
    inject_start = text.index('function injectLines(')
    foreach_start = text.index('.forEach(function (ln)', inject_start)
    call_site = text.index('removeBlankStarterLine', inject_start)
    assert inject_start < call_site < foreach_start, (
        'injectLines() must call window.removeBlankStarterLine() BEFORE appending the PO/RR\'s '
        'own lines via the forEach, not after')
