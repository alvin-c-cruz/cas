"""Output-VAT bucket allocation shared by the Sales Invoice posting path and the
credit/debit memo JE builder.

Both feed an invoice-shaped object (``.vat_amount`` plus ``.line_items`` each
with ``.vat_amount`` / ``.vat_category``). Living here -- in the posting service
package, below the view layer -- lets ``app/sales_memos/je.py`` import it
directly, replacing the old lazy ``from app.sales_invoices.views import
_output_vat_buckets`` that only existed to dodge a circular import (R4 Phase 1).
"""
from decimal import Decimal

from app.sales_vat_categories.models import SalesVATCategory
from app.posting.buckets import group_tax_buckets, reconcile_buckets_to_total


def output_vat_buckets(doc):
    """Group output VAT by SalesVATCategory.output_vat_account, reconciled to the
    document's ``vat_amount``.

    Returns a sorted list of ``(Account, Decimal)`` pairs. Raises ``ValueError``
    if a VAT-bearing line's category has no output tax account. Behaviour is
    identical to the historical ``sales_invoices._output_vat_buckets``.
    """
    if Decimal(str(doc.vat_amount)) <= 0:
        return []

    categories = {c.code: c for c in SalesVATCategory.query.all()}

    def _account_of(item):
        cat = categories.get(item.vat_category)
        return cat.output_vat_account if cat else None

    def _missing_account(item):
        cat = categories.get(item.vat_category)
        label = cat.code if cat else (item.vat_category or 'unknown')
        return (f"VAT category '{label}' has no Output Tax account configured. "
                "Set it in VAT Categories before posting.")

    buckets = group_tax_buckets(
        doc.line_items,
        amount_of=lambda item: item.vat_amount,
        account_of=_account_of,
        amount_predicate=lambda amt: amt > Decimal('0.00'),
        on_missing_account=_missing_account,
    )
    return reconcile_buckets_to_total(
        buckets, doc.vat_amount, only_if=True, largest_by='amount',
        allow_negative=False,
        negative_error=(
            'VAT override is too far below the computed VAT to allocate '
            'across output tax accounts.'),
    )
