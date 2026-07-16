"""Input-VAT bucket allocation shared by the Accounts Payable posting path and the
purchase (Vendor Debit Memo) JE builder.

Mirror of ``app/posting/sales_vat.py::output_vat_buckets`` for the buy side. Both
feed a bill-shaped object (``.vat_amount`` plus ``.line_items`` each with
``.vat_amount`` / ``.vat_category``). Living here -- in the posting service
package, below the view layer -- lets ``app/purchase_memos/je.py`` import it
directly without reaching into ``app/accounts_payable/views.py``'s private
``_input_vat_buckets`` (which stays as-is; extracting/de-duplicating it is out of
scope here -- see ``docs/superpowers/specs/2026-07-14-vendor-debit-memo-design.md``).
"""
from decimal import Decimal

from app.vat_categories.models import VATCategory
from app.posting.buckets import group_tax_buckets, reconcile_buckets_to_total


def input_vat_buckets(doc):
    """Group input VAT by VATCategory.input_vat_account, reconciled to the
    document's ``vat_amount``.

    Returns a sorted list of ``(Account, Decimal)`` pairs. Raises ``ValueError``
    if a VAT-bearing line's category has no input tax account. Behaviour mirrors
    ``app.accounts_payable.views._input_vat_buckets``.
    """
    if Decimal(str(doc.vat_amount)) <= 0:
        return []

    categories = {c.code: c for c in VATCategory.query.all()}

    def _account_of(item):
        cat = categories.get(item.vat_category)
        return cat.input_vat_account if cat else None

    def _missing_account(item):
        cat = categories.get(item.vat_category)
        label = cat.code if cat else (item.vat_category or 'unknown')
        return (f"VAT category '{label}' has no Input Tax account configured. "
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
            'across input tax accounts.'),
    )
