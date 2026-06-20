"""POV-aware Withholding Tax picker label. Sales documents show the seller-POV
sales_name (falling back to the buyer-POV name when blank); purchase documents
show name."""


def wt_label(wt_dict, pov='buyer'):
    code = wt_dict.get('code', '')
    if pov == 'sales':
        text = wt_dict.get('sales_name') or wt_dict.get('name', '')
    else:
        text = wt_dict.get('name', '')
    return f'{code} — {text}'
