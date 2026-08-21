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


def test_customer_label_is_not_inverted_any_more():
    body = _rule(SO, '.customer-header')
    assert '#fff' not in body and 'white' not in body, 'the label is still white text'
    assert '#222' not in body, 'the label still sits on the dark block'


def test_customer_label_still_reads_as_a_header():
    """CONTROL: "black" was about colour, not about flattening it entirely.

    Dropping the whole rule would satisfy the test above while losing the bold
    that distinguishes the section header from the fields under it.
    """
    assert re.search(r'font-weight:\s*700', _rule(SO, '.customer-header'))


def test_no_border_between_the_label_and_the_name():
    """BOTH sides, because collapsed borders merge.

    Mutation target: remove only the header's border-bottom and the name cell's
    own border-top is still drawn -- the line stays on the page while the CSS
    reads as fixed.
    """
    assert re.search(r'border-bottom:\s*none', _rule(SO, '.customer-header')), \
        'the CUSTOMER cell still draws its bottom border'
    assert re.search(r'border-top:\s*none', _rule(SO, '.customer-name')), \
        'the customer-name cell still draws its top border'


def test_the_name_cell_actually_carries_the_class():
    """A rule for .customer-name applies to nothing unless the <td> uses it."""
    html = io.open(SO, encoding='utf-8').read()
    body = html[html.index('</style>'):]
    m = re.search(r'class="label customer-header">CUSTOMER</td></tr>\s*'
                  r'<tr><td colspan="2" class="([^"]*)"', body)
    assert m, 'the CUSTOMER row is no longer followed by the name row'
    assert 'customer-name' in m.group(1).split()


@pytest.mark.parametrize('label,rel,selector', SIBLINGS, ids=[s[0] for s in SIBLINGS])
def test_the_other_documents_keep_their_dark_header(label, rel, selector):
    """CONTROL / scope pin: the directive named the SO only.

    If these should match later, that is a decision to take on purpose -- and
    this is the test that has to be edited to take it.
    """
    body = _rule(APP / rel, '.' + selector)
    assert '#222' in body and '#fff' in body, \
        f'{label} lost its dark header -- was that intended?'
