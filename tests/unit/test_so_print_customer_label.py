"""The SO printout's CUSTOMER label.

Owner directive 2026-08-21: "CUSTOMER label color should be black too. remove
the border between the customer label and the customer name."

It was white on a #222 block, the only inverted cell in the info table -- every
other label (TIN, Address, PO No.) is black on the shared #f0f0f0 `.label`
background. "Black too" means: look like those. So the inverted overrides go and
the cell falls back to `.label`, keeping only its heavier weight.

The border between the CUSTOMER cell and the customer-name cell below it comes
from `.info-row td { border: 1px solid #aaa }`, which borders every cell on all
four sides. Under `border-collapse: collapse` two adjacent borders merge into
one, so removing it takes BOTH sides -- the header's bottom and the name's top.
Killing only one leaves the neighbour's border drawn, which is the trap here.

SUPERSEDED IN PART 2026-08-31: CUSTOMER became an ordinary label-left /
value-right row, so the dedicated `.customer-header` class is gone and the
"remove the border between label and name" half no longer applies -- in the new
shape that divider is the same vertical border every other field has. What
survives is the requirement the directive was really about: the label is black
on the shared grey, not inverted. See test_so_print_customer_row.py.

SCOPE: the SO only. The same inverted-header pattern is in five other
documents (SI, Quotation, Cash Receipt "RECEIVED FROM", AP "VENDOR", CD
"PAY TO"). The directive named the SO, and this is a style preference rather
than a defect, so the others are pinned UNCHANGED below -- that assertion is
where the decision to sweep them gets made deliberately, not by accident.
"""
import io
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]

APP = Path(__file__).resolve().parents[2] / 'app'
SO = APP / 'sales_orders/templates/sales_orders/print.html'

#: the five documents that keep the inverted dark header
SIBLINGS = [
    ('sales_invoice', 'sales_invoices/templates/sales_invoices/print.html', 'customer-header'),
    ('quotation', 'quotations/templates/quotations/print.html', 'customer-header'),
    ('cash_receipt', 'cash_receipts/templates/cash_receipts/print.html', 'customer-header'),
    ('accounts_payable', 'accounts_payable/templates/accounts_payable/print.html', 'vendor-header'),
    ('cash_disbursement', 'cash_disbursements/templates/cash_disbursements/print.html', 'vendor-header'),
]

COMMENT = re.compile(r'/\*.*?\*/', re.S)


def _rule(path, selector):
    css = io.open(path, encoding='utf-8').read()
    css = COMMENT.sub('', css[css.index('<style>'):css.index('</style>')])
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    assert m, f'{selector} not found in {path.name}'
    return m.group(1)


def test_the_customer_label_uses_the_shared_grey_label_cell():
    """The 2026-08-21 directive -- "CUSTOMER label color should be black too" --
    still holds, it is just satisfied differently now.

    That directive was met by overriding a dedicated `.customer-header` class.
    The 2026-08-31 directive then made CUSTOMER an ordinary label-left /
    value-right row, so the cell simply IS a `.label` like TIN or PO No. and the
    override has nothing left to override. Asserting the outcome (it uses the
    shared class) rather than the old mechanism keeps the original requirement
    pinned without pinning a class that no longer exists.
    """
    html = io.open(SO, encoding='utf-8').read()
    body = html[html.index('</style>'):]
    assert re.search(r'<td class="label">CUSTOMER</td>', body),         'CUSTOMER is not rendered as a shared .label cell'
    assert 'customer-header' not in body, 'the retired banner class is back'


def test_the_customer_name_cell_carries_its_class():
    """A rule for .customer-name applies to nothing unless the <td> uses it."""
    html = io.open(SO, encoding='utf-8').read()
    body = html[html.index('</style>'):]
    assert re.search(r'<td class="customer-name">', body),         'the customer name cell lost its class'


def test_the_border_between_label_and_name_is_now_the_ordinary_field_divider():
    """SUPERSEDED, deliberately: 2026-08-21 also said "remove the border between
    the customer label and the customer name".

    That made sense when they were two STACKED rows and the border was a
    horizontal line splitting one logical field. The 2026-08-31 directive asked
    for the standard label-left / value-right shape, and in that shape the
    divider between a label and its value is the same vertical border every
    other field has. The newer directive wins; the older one is recorded here so
    the reversal reads as a decision rather than a regression.
    """
    css = io.open(SO, encoding='utf-8').read()
    css = COMMENT.sub('', css[css.index('<style>'):css.index('</style>')])
    assert not re.search(r'\.customer-name \{[^}]*border-top:\s*none', css),         'a leftover border-top:none would now erase a real field divider'


@pytest.mark.parametrize('label,rel,selector', SIBLINGS, ids=[s[0] for s in SIBLINGS])
def test_the_other_documents_keep_their_dark_header(label, rel, selector):
    """CONTROL / scope pin: the directive named the SO only.

    If these should match later, that is a decision to take on purpose -- and
    this is the test that has to be edited to take it.
    """
    body = _rule(APP / rel, '.' + selector)
    assert '#222' in body and '#fff' in body, \
        f'{label} lost its dark header -- was that intended?'
