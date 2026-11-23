"""Payment terms: what is stored, and what people read.

TERMS-1 A (owner, 22 Nov 2026: "the change Net 30 to 30 DAYS, this is the convention that the users wanted";
"A: "30 DAYS" labels only, all clients"): every form, page and print shows 15 / 30 / 45 / 60 / 90 DAYS, while the
stored values stay "Net 30" etc. -- no record changes, and the SI and AP due-date fill keeps reading the number out of
them (recomputeDueDate). Cash on Delivery and Advance Payment read as they are.

One list for every form that asks for terms (customers, vendors, sales orders, sales invoices, AP vouchers, purchase
orders, quotations), and one filter (`terms_label`, registered in app/__init__.py) for every page that shows one.
"""
import re

#: The stored values, in the order the pickers list them.
PAYMENT_TERMS = ('Net 15', 'Net 30', 'Net 45', 'Net 60', 'Net 90', 'Cash on Delivery', 'Advance Payment')

_NET_DAYS = re.compile(r'^\s*net\s+(\d+)\s*$', re.IGNORECASE)


def terms_label(value):
    """How a stored term reads: "Net 30" -> "30 DAYS"; anything else as it is; nothing -> ''."""
    if not value:
        return ''
    m = _NET_DAYS.match(str(value))
    return f'{m.group(1)} DAYS' if m else value


#: (stored value, label) for the SelectFields.
PAYMENT_TERMS_CHOICES = [(v, terms_label(v)) for v in PAYMENT_TERMS]
