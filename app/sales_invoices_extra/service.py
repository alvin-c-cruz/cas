"""Creation and posting for SalesInvoiceExtra -- see models.py module docstring
for why this is a separate model/flow from app.sales_invoices (no VAT/WHT).
"""
from decimal import Decimal

from app import db
from app.utils import ph_now


def create_si_extra_from_dr(dr, actor_user_id, is_cash_sale=False):
    """Build a draft SalesInvoiceExtra + line items from an already-delivered
    EXTRA-branch DeliveryReceipt, sourcing product/qty/price from the DR's own
    line items (which read through to SalesOrderItem.unit_price -- the single
    source of truth for price on this side of the system).

    invoice_number is always set to dr.dr_number (owner convention: "Extra use
    the same DR# for recording on SI") -- one SalesInvoiceExtra per DR.
    """
    from app.sales_invoices_extra.models import SalesInvoiceExtra, SalesInvoiceExtraItem
    from app.customers.models import Customer

    existing = SalesInvoiceExtra.query.filter_by(delivery_receipt_id=dr.id).first()
    if existing is not None:
        return existing

    customer = db.session.get(Customer, dr.customer_id)
    due_date = dr.delivery_date

    invoice = SalesInvoiceExtra(
        branch_id=dr.branch_id,
        invoice_number=dr.dr_number,
        invoice_date=dr.delivery_date,
        due_date=due_date,
        customer_id=customer.id,
        customer_name=customer.name,
        customer_address=customer.address,
        payment_terms=customer.payment_terms,
        reference=f'Source DR#{dr.dr_number}',
        notes='',
        delivery_receipt_id=dr.id,
        is_cash_sale=is_cash_sale,
        status='draft',
        created_by_id=actor_user_id,
    )
    for i, dr_item in enumerate(dr.line_items, start=1):
        soi = dr_item.sales_order_item
        item = SalesInvoiceExtraItem(
            line_number=i,
            description=soi.product.name,
            product_id=soi.product_id,
            quantity=dr_item.delivered_quantity,
            unit_price=soi.unit_price,
            unit_of_measure_id=soi.unit_of_measure_id,
            uom_text=soi.uom_text,
        )
        item.calculate_amounts()
        invoice.line_items.append(item)

    invoice.calculate_totals()
    db.session.add(invoice)
    db.session.flush()
    return invoice


def post_si_extra_je(invoice, user_id):
    """Create the SI-Extra JE: Dr AR-Trade (or Cash) / Cr EXTRA Sales Revenue.
    Flat 2-line entry, no VAT/WHT lines ever (see models.py docstring)."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_entry_number
    from app.posting.control_accounts import get_control_account

    if invoice.is_cash_sale:
        debit_account = invoice.cash_account
        if debit_account is None:
            raise ValueError(
                f'SI-Extra {invoice.invoice_number} is marked cash sale but has no cash_account_id set.')
    else:
        debit_account = invoice.ar_trade_account or get_control_account('ar_trade')

    revenue_account = invoice.sales_revenue_account or get_control_account('extra_sales_revenue')

    je_status = 'posted' if invoice.status == 'posted' else 'draft'
    entry_number = generate_entry_number(invoice.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=invoice.invoice_date,
        description=f'SI-Extra {invoice.invoice_number} — {invoice.customer_name}',
        reference=invoice.invoice_number,
        entry_type='sale',
        branch_id=invoice.branch_id,
        created_by_id=user_id,
        status=je_status,
        posted_by_id=user_id if je_status == 'posted' else None,
        posted_at=ph_now() if je_status == 'posted' else None,
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00'),
    )
    db.session.add(je)
    db.session.flush()

    total = Decimal(str(invoice.total_amount))
    debit_line = JournalEntryLine(
        entry_id=je.id, line_number=1,
        account_id=debit_account.id,
        description=f'{"Cash" if invoice.is_cash_sale else "AR"}: {invoice.invoice_number} — {invoice.customer_name}',
        debit_amount=total,
        credit_amount=Decimal('0.00'),
    )
    credit_line = JournalEntryLine(
        entry_id=je.id, line_number=2,
        account_id=revenue_account.id,
        description=f'EXTRA Sales: {invoice.invoice_number}',
        debit_amount=Decimal('0.00'),
        credit_amount=total,
    )
    db.session.add(debit_line)
    db.session.add(credit_line)
    db.session.flush()

    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f'SI-Extra JE is not balanced (debit={je.total_debit}, credit={je.total_credit}).')
    return je
