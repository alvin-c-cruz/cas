"""Regression tests for BUG-SI-PULL-DR-LEAVES-BLANK-LINE: pulling a DR onto a Sales Invoice
must remove the form's default blank starter line instead of leaving it orphaned as line 1."""
import pathlib


def test_form_html_exposes_remove_blank_starter_line_helper(client, accountant_user):
    with client:
        client.post('/login', data={'username': accountant_user.username,
                                    'password': 'accountant123'}, follow_redirects=True)
        resp = client.get('/sales-invoices/create')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'window.removeBlankStarterLine' in body, (
            'form.html must expose window.removeBlankStarterLine for si_dr_billing.js to call')


def test_si_dr_billing_js_calls_remove_blank_starter_line_before_pulling():
    js_path = (pathlib.Path(__file__).resolve().parents[2]
              / 'app' / 'static' / 'js' / 'si_dr_billing.js')
    text = js_path.read_text(encoding='utf-8')
    pull_start = text.index('function pull(')
    foreach_start = text.index('.forEach(function (ln)', pull_start)
    call_site = text.index('removeBlankStarterLine', pull_start)
    assert pull_start < call_site < foreach_start, (
        'pull() must call window.removeBlankStarterLine() BEFORE appending the DR\'s own '
        'lines via the forEach, not after')
