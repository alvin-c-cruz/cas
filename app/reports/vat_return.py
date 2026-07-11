"""BIR 2550Q box taxonomy + live schedules folded from vat_lines().

Sales nature -> Part I (12A-12D); purchase nature -> Part II (18A/B-18G, plus
exempt/zero-rated). Unclassified is always its own bucket, always footed into
the total, never folded into vatable. Pure functions; no ORM objects escape.
"""
from decimal import Decimal

from app.reports.vat_lines import vat_lines, UNCLASSIFIED
from app.vat_settlement.service import quarter_bounds

Z = Decimal('0.00')

# --- Part I: Computation of Output Tax -------------------------------------
SALES_BOX_BY_NATURE = {
    'regular': '12A',
    'zero_export': '12B',
    'zero_other': '12B',
    'exempt': '12C',
    'government': '12D',
    UNCLASSIFIED: 'unclassified',
}
SALES_BOX_ORDER = ['12A', '12B', '12C', '12D']
SALES_BOX_LABEL = {
    '12A': 'Vatable Sales',
    '12B': 'Zero-Rated Sales',
    '12C': 'Exempt Sales',
    '12D': 'Sales to Government',
}

# --- Part II: Computation of Input Tax -------------------------------------
INPUT_BOX_BY_NATURE = {
    'capital_goods': '18AB',       # not split at 1,000,000 (footnote)
    'domestic_goods': '18C',
    'importation': '18D',
    'domestic_services': '18E',
    'nonresident_services': '18F',
    'not_qualified': '18G',        # base only, no input tax
    'exempt': 'exempt',
    'zero_rated': 'zero_rated',
    UNCLASSIFIED: 'unclassified',
}
INPUT_BOX_ORDER = ['18AB', '18C', '18D', '18E', '18F', '18G', 'exempt', 'zero_rated']
INPUT_BOX_LABEL = {
    '18AB': 'Capital Goods',
    '18C': 'Domestic Purchase of Goods',
    '18D': 'Importation of Goods',
    '18E': 'Domestic Purchase of Services',
    '18F': 'Services Rendered by Non-Residents',
    '18G': 'Not Qualified for Input Tax',
    'exempt': 'VAT-Exempt Purchases',
    'zero_rated': 'Zero-Rated Purchases',
}


def _build_schedule(lines, box_by_nature, box_order, box_label):
    acc = {box: {'base': Z, 'tax': Z} for box in box_order}
    unclassified = {'base': Z, 'tax': Z, 'count': 0}
    for ln in lines:
        box = box_by_nature.get(ln.nature, 'unclassified')
        target = acc.get(box)
        if target is None:                       # unclassified / unknown nature
            unclassified['base'] += ln.base
            unclassified['tax'] += ln.vat_amount
            unclassified['count'] += 1
        else:
            target['base'] += ln.base
            target['tax'] += ln.vat_amount
    rows = [{'box': b, 'label': box_label[b],
             'base': acc[b]['base'], 'tax': acc[b]['tax']} for b in box_order]
    if unclassified['base'] or unclassified['tax'] or unclassified['count']:
        rows.append({'box': '--', 'label': 'Unclassified',
                     'base': unclassified['base'], 'tax': unclassified['tax'],
                     'unclassified': True})
    total_base = sum((r['base'] for r in rows), Z)
    total_tax = sum((r['tax'] for r in rows), Z)
    return {'rows': rows, 'total_base': total_base, 'total_tax': total_tax,
            'unclassified_count': unclassified['count']}


def build_vat_return_schedules(year, quarter):
    """Part I / Part II schedules for the quarter, live from posted document lines."""
    qstart, qend = quarter_bounds(year, quarter)
    sales = _build_schedule(vat_lines(qstart, qend, 'sales'),
                            SALES_BOX_BY_NATURE, SALES_BOX_ORDER, SALES_BOX_LABEL)
    inp = _build_schedule(vat_lines(qstart, qend, 'purchases'),
                          INPUT_BOX_BY_NATURE, INPUT_BOX_ORDER, INPUT_BOX_LABEL)
    return {'sales_schedule': sales, 'input_schedule': inp}


def reconcile_vat_return(output_gl, input_gl, schedules):
    """Tie the document side (schedules) to the GL side (settlement position).

    output_gl / input_gl are None when compute_vat_position() could not run
    (e.g. unsettled prior quarter). A None GL side is never 'in balance'.
    """
    output_docs = schedules['sales_schedule']['total_tax']
    input_docs = schedules['input_schedule']['total_tax']
    unclassified_count = (schedules['sales_schedule']['unclassified_count']
                          + schedules['input_schedule']['unclassified_count'])
    in_balance = (output_gl is not None and input_gl is not None
                  and output_gl == output_docs and input_gl == input_docs)
    return {'output_gl': output_gl, 'output_docs': output_docs,
            'input_gl': input_gl, 'input_docs': input_docs,
            'unclassified_count': unclassified_count, 'in_balance': in_balance}
