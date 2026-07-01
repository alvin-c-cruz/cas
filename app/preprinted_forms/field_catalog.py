"""Field catalog for pre-printed voucher forms (P-69).

Single source of truth for which data fields each voucher type (SI, CR, CD,
AP, JV) can place on a pre-printed form overlay, plus a resolver per field.
The designer (Task 5) offers only these fields; the PDF renderer (Task 3)
resolves values only through ``resolve_field`` / ``resolve_line_value``.

Dates format as ``%m/%d/%Y``; money formats as bare numbers via
``'{:,.2f}'`` (no currency sign — the paper form carries any peso label).
"""
from decimal import Decimal, InvalidOperation

DATE_FORMAT = '%m/%d/%Y'


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_date(value):
    if not value:
        return ''
    try:
        return value.strftime(DATE_FORMAT)
    except AttributeError:
        return str(value)


def _fmt_money(value):
    if value is None:
        return ''
    try:
        return '{:,.2f}'.format(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return ''


def _fmt_text(value):
    return value if value else ''


def _user_name(user):
    return user.full_name if user else ''


def _branch_name(record):
    branch = getattr(record, 'branch', None)
    return branch.name if branch else ''


def _prepared_by(record):
    return _user_name(getattr(record, 'created_by', None))


def _approved_by(record):
    return _user_name(getattr(record, 'posted_by', None))


def _account_code(line):
    account = getattr(line, 'account', None)
    return account.code if account else ''


def _account_name(line):
    account = getattr(line, 'account', None)
    return account.name if account else ''


# ---------------------------------------------------------------------------
# amount_in_words
# ---------------------------------------------------------------------------

_ONES = ('', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine')
_TEENS = ('Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
          'Seventeen', 'Eighteen', 'Nineteen')
_TENS = ('', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety')
_SCALES = ('', 'Thousand', 'Million', 'Billion')


def _three_digits_to_words(n):
    """Convert an integer 0-999 to words (no trailing/leading spaces)."""
    words = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        words.append(f'{_ONES[hundreds]} Hundred')
    if rest:
        if rest < 10:
            words.append(_ONES[rest])
        elif rest < 20:
            words.append(_TEENS[rest - 10])
        else:
            tens, ones = divmod(rest, 10)
            if ones:
                words.append(f'{_TENS[tens]}-{_ONES[ones]}')
            else:
                words.append(_TENS[tens])
    return ' '.join(words)


def _int_to_words(n):
    """Convert a non-negative integer to words."""
    if n == 0:
        return 'Zero'
    chunks = []
    scale_idx = 0
    while n > 0:
        n, chunk = divmod(n, 1000)
        if chunk:
            chunk_words = _three_digits_to_words(chunk)
            scale = _SCALES[scale_idx]
            chunks.append(f'{chunk_words} {scale}'.strip())
        scale_idx += 1
    return ' '.join(reversed(chunks))


def amount_in_words(value):
    """Render a peso amount as words, e.g. 'One Thousand Two Hundred Thirty
    Four Pesos and 50/100'. Pure Python, no external dependency."""
    try:
        amount = Decimal(str(value)) if value is not None else Decimal('0')
    except (InvalidOperation, ValueError, TypeError):
        amount = Decimal('0')
    if amount < 0:
        amount = -amount
    amount = amount.quantize(Decimal('0.01'))
    pesos = int(amount)
    centavos = int((amount - pesos) * 100)

    peso_words = _int_to_words(pesos)
    peso_label = 'Peso' if pesos == 1 else 'Pesos'
    result = f'{peso_words} {peso_label}'
    result += f' and {centavos:02d}/100'
    return result


# ---------------------------------------------------------------------------
# FieldDef builders
# ---------------------------------------------------------------------------

def _hf(key, label, resolve):
    """Header FieldDef."""
    return {'key': key, 'label': label, 'resolve': resolve}


def _lf(key, label, resolve):
    """Line-column FieldDef."""
    return {'key': key, 'label': label, 'resolve': resolve}


def _attr_str(attr_name):
    def _resolve(record):
        return _fmt_text(getattr(record, attr_name, None))
    return _resolve


def _attr_date(attr_name):
    def _resolve(record):
        return _fmt_date(getattr(record, attr_name, None))
    return _resolve


def _attr_money(attr_name):
    def _resolve(record):
        return _fmt_money(getattr(record, attr_name, None))
    return _resolve


def _amount_in_words_of(attr_name):
    def _resolve(record):
        return amount_in_words(getattr(record, attr_name, None))
    return _resolve


def _display_number(record):
    return _fmt_text(getattr(record, 'display_number', None))


# ---------------------------------------------------------------------------
# Line-column resolvers (shared shape across SI/CR/CD/AP: description,
# quantity, unit_price, amount(line_total), account_code, account_name)
# ---------------------------------------------------------------------------

def _line_description(line):
    return _fmt_text(getattr(line, 'description', None))


def _line_quantity(line):
    qty = getattr(line, 'quantity', None)
    if qty is None:
        return ''
    try:
        return '{:,.4f}'.format(Decimal(str(qty))).rstrip('0').rstrip('.')
    except (InvalidOperation, ValueError, TypeError):
        return ''


def _line_unit_price(line):
    return _fmt_money(getattr(line, 'unit_price', None))


def _line_amount(line):
    # NOTE: resolves to line_total (VAT-inclusive derived total), not the
    # raw `amount` column — verified against SalesInvoiceItem, APLineItem,
    # CRVRevenueLine, CDVExpenseLine.
    return _fmt_money(getattr(line, 'line_total', None))


def _standard_line_columns():
    return [
        _lf('description', 'Description', _line_description),
        _lf('quantity', 'Quantity', _line_quantity),
        _lf('unit_price', 'Unit Price', _line_unit_price),
        _lf('amount', 'Amount', _line_amount),
        _lf('account_code', 'Account Code', _account_code),
        _lf('account_name', 'Account Name', _account_name),
    ]


# ---------------------------------------------------------------------------
# FIELD_CATALOG
# ---------------------------------------------------------------------------

FIELD_CATALOG = {
    'SI': {
        'header': [
            _hf('number', 'Invoice Number', _attr_str('invoice_number')),
            _hf('date', 'Invoice Date', _attr_date('invoice_date')),
            _hf('payee', 'Customer Name', _attr_str('customer_name')),
            _hf('payee_tin', 'Customer TIN', _attr_str('customer_tin')),
            _hf('reference', 'Reference', _attr_str('reference')),
            _hf('particulars', 'Particulars', _attr_str('notes')),
            _hf('subtotal', 'Subtotal', _attr_money('subtotal')),
            _hf('vat_amount', 'VAT Amount', _attr_money('vat_amount')),
            _hf('withholding_tax_amount', 'Withholding Tax', _attr_money('withholding_tax_amount')),
            _hf('total', 'Total', _attr_money('total_amount')),
            _hf('amount_in_words', 'Amount in Words', _amount_in_words_of('total_amount')),
            _hf('prepared_by', 'Prepared By', _prepared_by),
            _hf('approved_by', 'Approved By', _approved_by),
            _hf('branch', 'Branch', _branch_name),
        ],
        'line_columns': _standard_line_columns(),
    },
    'CR': {
        'header': [
            _hf('number', 'CRV Number', _attr_str('crv_number')),
            _hf('date', 'CRV Date', _attr_date('crv_date')),
            _hf('payee', 'Customer Name', _attr_str('customer_name')),
            _hf('check_number', 'Check Number', _attr_str('check_number')),
            _hf('check_date', 'Check Date', _attr_date('check_date')),
            _hf('particulars', 'Particulars', _attr_str('notes')),
            _hf('total', 'Total', _attr_money('total_amount')),
            _hf('amount_in_words', 'Amount in Words', _amount_in_words_of('total_amount')),
            _hf('prepared_by', 'Prepared By', _prepared_by),
            _hf('approved_by', 'Approved By', _approved_by),
            _hf('branch', 'Branch', _branch_name),
        ],
        'line_columns': _standard_line_columns(),
    },
    'CD': {
        'header': [
            _hf('number', 'CDV Number', _attr_str('cdv_number')),
            _hf('date', 'CDV Date', _attr_date('cdv_date')),
            _hf('payee', 'Vendor Name', _attr_str('vendor_name')),
            _hf('check_number', 'Check Number', _attr_str('check_number')),
            _hf('check_date', 'Check Date', _attr_date('check_date')),
            _hf('particulars', 'Particulars', _attr_str('notes')),
            _hf('total', 'Total', _attr_money('total_amount')),
            _hf('amount_in_words', 'Amount in Words', _amount_in_words_of('total_amount')),
            _hf('prepared_by', 'Prepared By', _prepared_by),
            _hf('approved_by', 'Approved By', _approved_by),
            _hf('branch', 'Branch', _branch_name),
        ],
        'line_columns': _standard_line_columns(),
    },
    'AP': {
        'header': [
            _hf('number', 'AP Number', _attr_str('ap_number')),
            _hf('date', 'AP Date', _attr_date('ap_date')),
            _hf('payee', 'Vendor Name', _attr_str('vendor_name')),
            _hf('payee_tin', 'Vendor TIN', _attr_str('vendor_tin')),
            _hf('vendor_invoice_number', 'Vendor Invoice Number', _attr_str('vendor_invoice_number')),
            _hf('reference', 'Reference', _attr_str('reference')),
            _hf('particulars', 'Particulars', _attr_str('notes')),
            _hf('subtotal', 'Subtotal', _attr_money('subtotal')),
            _hf('vat_amount', 'VAT Amount', _attr_money('vat_amount')),
            _hf('withholding_tax_amount', 'Withholding Tax', _attr_money('withholding_tax_amount')),
            _hf('total', 'Total', _attr_money('total_amount')),
            _hf('amount_in_words', 'Amount in Words', _amount_in_words_of('total_amount')),
            _hf('prepared_by', 'Prepared By', _prepared_by),
            _hf('approved_by', 'Approved By', _approved_by),
            _hf('branch', 'Branch', _branch_name),
        ],
        'line_columns': _standard_line_columns(),
    },
    'JV': {
        'header': [
            _hf('number', 'JV Number', _display_number),
            _hf('date', 'Entry Date', _attr_date('entry_date')),
            _hf('particulars', 'Particulars', _attr_str('description')),
            _hf('reference', 'Reference', _attr_str('reference')),
            _hf('total', 'Total', _attr_money('total_debit')),
            _hf('amount_in_words', 'Amount in Words', _amount_in_words_of('total_debit')),
            _hf('prepared_by', 'Prepared By', _prepared_by),
            _hf('approved_by', 'Approved By', _approved_by),
            _hf('branch', 'Branch', _branch_name),
        ],
        'line_columns': [
            _lf('account_code', 'Account Code', _account_code),
            _lf('account_name', 'Account Name', _account_name),
            _lf('line_description', 'Description', _line_description),
            _lf('debit', 'Debit', lambda line: _fmt_money(getattr(line, 'debit_amount', None))),
            _lf('credit', 'Credit', lambda line: _fmt_money(getattr(line, 'credit_amount', None))),
        ],
    },
}


# ---------------------------------------------------------------------------
# Line collections per voucher type
# ---------------------------------------------------------------------------

_LINE_ATTR = {
    'SI': 'line_items',
    'CR': 'revenue_lines',
    'CD': 'expense_lines',
    'AP': 'line_items',
    'JV': 'lines',
}


def iter_lines(voucher_type, record):
    """Return the line-item collection for a voucher record, as a list."""
    attr_name = _LINE_ATTR.get(voucher_type)
    if attr_name is None or record is None:
        return []
    collection = getattr(record, attr_name, None)
    if collection is None:
        return []
    if voucher_type == 'JV':
        # JournalEntry.lines is lazy='dynamic' -> AppenderQuery
        return collection.all()
    return list(collection)


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

def _find_field(fields, key):
    for f in fields:
        if f['key'] == key:
            return f
    return None


def resolve_field(voucher_type, key, record):
    """Resolve a header field value for a voucher record. Returns '' for an
    unknown voucher type or key."""
    cat = FIELD_CATALOG.get(voucher_type)
    if cat is None:
        return ''
    field = _find_field(cat['header'], key)
    if field is None:
        return ''
    try:
        return field['resolve'](record)
    except Exception:
        return ''


def resolve_line_value(voucher_type, key, line):
    """Resolve a line-column field value for a line item. Returns '' for an
    unknown voucher type or key."""
    cat = FIELD_CATALOG.get(voucher_type)
    if cat is None:
        return ''
    field = _find_field(cat['line_columns'], key)
    if field is None:
        return ''
    try:
        return field['resolve'](line)
    except Exception:
        return ''
