"""Merge two single-period statement dicts into a two-column (MTD + YTD) shape.

Both inputs come from the same generator with the same section spec, so sections
align by index. Lines are unioned by account code (IS) or line name (CF); a value
present in only one column is zero-filled on the other.
"""


def _union_by(a_items, b_items, key, a_field, b_field):
    """Order-preserving union of two dict lists by `key`.

    Emits one row per distinct key (a's order first, then b-only keys), each as
    {**identity from whichever side has it, 'mtd': a_val, 'ytd': b_val}.
    """
    b_by = {i[key]: i for i in b_items}
    out, seen = [], set()
    for i in a_items:
        k = i[key]
        seen.add(k)
        b = b_by.get(k)
        row = dict(i)
        row['mtd'] = i.get(a_field, 0.0)
        row['ytd'] = (b.get(b_field, 0.0) if b else 0.0)
        out.append(row)
    for i in b_items:
        k = i[key]
        if k in seen:
            continue
        row = dict(i)
        row['mtd'] = 0.0
        row['ytd'] = i.get(b_field, 0.0)
        out.append(row)
    return out


def _merge_children(a_children, b_children):
    rows = _union_by(a_children, b_children, key='code', a_field='amount', b_field='amount')
    for r in rows:
        r['mtd_amount'] = r.pop('mtd')
        r['ytd_amount'] = r.pop('ytd')
        r.pop('amount', None)
    return rows


def _merge_lines(a_lines, b_lines):
    a_by = {l['account_id']: l for l in a_lines}
    b_by = {l['account_id']: l for l in b_lines}
    order = list(a_by.keys()) + [k for k in b_by.keys() if k not in a_by]
    merged = []
    for aid in order:
        a = a_by.get(aid)
        b = b_by.get(aid)
        base = dict(a or b)
        base['mtd_amount'] = (a['total'] if a else 0.0)
        base['ytd_amount'] = (b['total'] if b else 0.0)
        base.pop('total', None)
        base['children'] = _merge_children((a or {}).get('children', []),
                                           (b or {}).get('children', []))
        merged.append(base)
    return merged


_IS_SCALARS = ('net_sales', 'gross_profit', 'operating_income', 'income_before_tax', 'net_income')


def merge_is_two_column(mtd, ytd):
    """Two-column Income Statement. See module docstring."""
    sections = []
    for sm, sy in zip(mtd['sections'], ytd['sections']):
        sec = {'key': sm['key'], 'label': sm['label'], 'sign': sm['sign'],
               'mtd_total': sm['total'], 'ytd_total': sy['total'],
               'lines': _merge_lines(sm['lines'], sy['lines'])}
        if sm.get('subtotal_label'):
            sec['subtotal_label'] = sm['subtotal_label']
            sec['mtd_subtotal'] = sm.get('subtotal', 0.0)
            sec['ytd_subtotal'] = sy.get('subtotal', 0.0)
        sections.append(sec)
    out = {'sections': sections,
           'mtd_start': mtd.get('period_start'), 'mtd_end': mtd.get('period_end'),
           'ytd_start': ytd.get('period_start'), 'as_of': ytd.get('period_end')}
    for k in _IS_SCALARS:
        out[k] = {'mtd': mtd.get(k, 0.0), 'ytd': ytd.get(k, 0.0)}
    return out


def _pair(a, b):
    return {'mtd': a, 'ytd': b}


def _merge_named_lines(a_lines, b_lines):
    rows = _union_by(a_lines, b_lines, key='name', a_field='amount', b_field='amount')
    for r in rows:
        r['mtd_amount'] = r.pop('mtd')
        r['ytd_amount'] = r.pop('ytd')
        r.pop('amount', None)
    return rows


def merge_cf_two_column(mtd, ytd):
    """Two-column Statement of Cash Flows. See module docstring."""
    return {
        'method': mtd.get('method', 'indirect'),
        'mtd_start': mtd.get('period_start'), 'mtd_end': mtd.get('period_end'),
        'ytd_start': ytd.get('period_start'), 'as_of': ytd.get('period_end'),
        'operating': {
            'net_income': _pair(mtd['operating']['net_income'], ytd['operating']['net_income']),
            'depreciation': _pair(mtd['operating']['depreciation'], ytd['operating']['depreciation']),
            'working_capital': _merge_named_lines(mtd['operating']['working_capital'],
                                                  ytd['operating']['working_capital']),
            'total': _pair(mtd['operating']['total'], ytd['operating']['total']),
        },
        'investing': {
            'lines': _merge_named_lines(mtd['investing']['lines'], ytd['investing']['lines']),
            'total': _pair(mtd['investing']['total'], ytd['investing']['total']),
        },
        'financing': {
            'lines': _merge_named_lines(mtd['financing']['lines'], ytd['financing']['lines']),
            'total': _pair(mtd['financing']['total'], ytd['financing']['total']),
        },
        'net_change': _pair(mtd['net_change'], ytd['net_change']),
        'cash_begin': _pair(mtd['cash_begin'], ytd['cash_begin']),
        'cash_end': _pair(mtd['cash_end'], ytd['cash_end']),
        'is_reconciled': bool(mtd.get('is_reconciled', True) and ytd.get('is_reconciled', True)),
        'difference': _pair(mtd.get('difference', 0.0), ytd.get('difference', 0.0)),
    }
