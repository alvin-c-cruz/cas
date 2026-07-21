"""Credit/Debit memo journal-entry builder.

Phase 1: credit memo only. A credit memo REVERSES the returned portion of the SI:
    Dr  Sales Returns & Allowances (contra-revenue)   net revenue reversed (subtotal - VAT)
    Dr  Output VAT (per output-VAT-account bucket)     VAT reversed
      Cr  Creditable WHT (control account)               WHT unwound
      Cr  {AR (control account) | cash account | Customer Credits}  destination (= gross - WHT)

AR and Creditable WHT are resolved via ``app.posting.control_accounts.get_control_account``
(settings-assigned), not hardcoded codes -- see BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS.

Follows the posted-JE-leg-vs-header invariant: the non-plug legs equal the memo header
buckets by construction; the destination is the reconciled residual (only sub-centavo
VAT-bucket rounding ever lands there).
"""
from decimal import Decimal

from app import db
from app.utils import ph_now
from app.journal_entries.utils import generate_entry_number
from app.sales_memos import service
from app.posting.sales_vat import output_vat_buckets
from app.posting.control_accounts import get_control_account
from app.stock_adjustments.service import post_movement, reverse_document_movements
from app.stock_adjustments.models import StockBalance


def _cm_line_chain_verified(li):
    """True if this SalesMemoItem's referenced Sales Invoice has at least one
    billed DeliveryReceipt carrying a line for the SAME product -- document-
    level proof that a real DR-driven COGS relief happened for this product
    under this invoice (R-03 slice 2a-v). Not a precise per-unit trace (there
    is no line-level SI<->DR link in this data model) -- a Sales Invoice can
    be created fully standalone with zero DR involvement, so this check
    exists specifically to avoid reversing COGS that was never expensed."""
    from app.delivery_receipts.models import DeliveryReceipt

    si_item = li.sales_invoice_item
    if si_item is None:
        return False
    drs = DeliveryReceipt.query.filter_by(sales_invoice_id=si_item.invoice_id).all()
    for dr in drs:
        for dr_li in dr.line_items:
            if dr_li.product_id == li.product_id:
                return True
    return False


def post_memo_je(memo, user_id, actor=None):
    """Build and return the memo's JournalEntry (draft or posted, matching memo.status).

    ``actor`` (the acting User) is required ONLY when a credit memo has a
    chain-verified, inventory-tracked line -- those lines post a real
    ``'sales_return'`` stock movement (which needs ``actor.id``). Existing callers
    passing just ``(memo, user_id)`` keep working: a memo with no such line never
    touches ``actor``. See R-03 slice 2a-v."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    if memo.memo_type not in ('credit', 'debit'):
        raise ValueError(f'Unknown memo_type {memo.memo_type!r}.')

    subtotal = Decimal(str(memo.subtotal or 0))
    vat_total = Decimal(str(memo.vat_amount or 0))
    wht_total = Decimal(str(memo.withholding_tax_amount or 0))
    total = Decimal(str(memo.total_amount or 0))
    net_revenue = subtotal - vat_total

    # Destination account (shared by both memo types).
    if memo.destination == 'ar':
        dest = get_control_account('ar_trade')
    elif memo.destination == 'cash_refund':
        dest = memo.cash_account
        if dest is None:
            raise ValueError('No cash account selected.')
    else:  # customer_credit
        dest = service.resolve_memo_account(service.CUSTOMER_CREDITS_KEY, 'Customer Credits/Advances')

    wt_account = get_control_account('creditable_wht') if wht_total > 0 else None

    doc_label = 'Credit Memo' if memo.memo_type == 'credit' else 'Debit Note'
    je_status = 'posted' if memo.status == 'posted' else 'draft'
    je = JournalEntry(
        entry_number=generate_entry_number(memo.branch_id),
        entry_date=memo.memo_date,
        description=f'{doc_label} {memo.memo_number} - {memo.customer_name}',
        reference=memo.memo_number, entry_type='sale', branch_id=memo.branch_id,
        created_by_id=user_id, status=je_status,
        posted_by_id=user_id if je_status == 'posted' else None,
        posted_at=ph_now() if je_status == 'posted' else None,
        is_balanced=False, total_debit=Decimal('0.00'), total_credit=Decimal('0.00'))
    db.session.add(je)
    db.session.flush()

    lines = []
    seq = {'n': 1}

    def add(acct_id, desc, debit, credit):
        line = JournalEntryLine(entry_id=je.id, line_number=seq['n'], account_id=acct_id,
                                description=desc, debit_amount=debit, credit_amount=credit)
        db.session.add(line)
        lines.append(line)
        seq['n'] += 1
        return line

    vat_bucket_total = Decimal('0.00')

    if memo.memo_type == 'credit':
        # Reverse the returned portion: Dr contra + Dr Output VAT; Cr WHT; Cr destination.
        contra = service.resolve_memo_account(service.SALES_RETURNS_KEY, 'Sales Returns & Allowances')
        if net_revenue > 0:
            add(contra.id, f'Sales Returns: {memo.memo_number}', net_revenue, Decimal('0.00'))
        for vat_acct, vat_amt in output_vat_buckets(memo):
            if vat_amt <= 0:
                continue
            add(vat_acct.id, f'Output VAT reversed: {memo.memo_number}', vat_amt, Decimal('0.00'))
            vat_bucket_total += vat_amt
        if wt_account is not None:
            add(wt_account.id, f'Creditable WHT reversed: {memo.memo_number}',
                Decimal('0.00'), wht_total)
        dest_line = add(dest.id, f'{memo.memo_number} - {memo.customer_name}',
                        Decimal('0.00'), total)

        # R-03 2a-v: ADD (never redirect) a real Dr inventory / Cr cogs pair for lines
        # with a genuine DR-driven COGS relief -- the sales-return COGS reversal is an
        # INDEPENDENT, additive effect alongside the revenue reversal above.
        #
        # Fail-closed ordering: resolve BOTH 'inventory' and 'cogs' control accounts
        # lazily, on the FIRST chain-verified+tracked line, strictly BEFORE that line's
        # post_movement. Resolving them after the movement loop would let a stock write
        # land before the control-account check could fire, breaking the "zero writes on
        # a missing account" guarantee (the bug the VDM side had to fix).
        inv_account = None
        cogs_account = None
        cogs_net = Decimal('0.00')
        for li in memo.line_items:
            if li.product_id is None or not li.product.track_inventory:
                continue
            if not _cm_line_chain_verified(li):
                continue
            qty = Decimal(str(li.quantity)) if li.quantity is not None else None
            if qty is None or qty <= 0:
                continue
            if actor is None:
                raise ValueError(
                    f'{memo.memo_number} has a chain-verified inventory line -- '
                    f'an actor is required to post the stock movement.')
            if inv_account is None:
                inv_account = get_control_account('inventory')   # raises if unassigned
                cogs_account = get_control_account('cogs')       # raises if unassigned
            # 'sales_return' is a POSITIVE/IN delta: compute_new_balance dereferences
            # in_unit_cost unconditionally for a positive move on a non-standard product,
            # so pass the product's CURRENT average (a no-op weighted-avg-with-itself;
            # ignored entirely for a standard-costed product). None would crash here.
            bal = StockBalance.query.filter_by(product_id=li.product_id,
                                               branch_id=memo.branch_id).first()
            current_avg = Decimal(str(bal.average_unit_cost)) if bal else Decimal('0.00')
            mv, _went_negative = post_movement(
                li.product, memo.branch_id, 'sales_return', qty, current_avg,
                'sales_memo', memo.id, f'{memo.memo_number} return: {li.product.code}',
                actor, journal_entry_id=je.id)
            cogs_net += abs(Decimal(str(mv.quantity))) * Decimal(str(mv.unit_cost))
        if cogs_net > 0:
            add(inv_account.id, f'Inventory returned: {memo.memo_number}', cogs_net, Decimal('0.00'))
            add(cogs_account.id, f'COGS reversed: {memo.memo_number}', Decimal('0.00'), cogs_net)
        plug_is_debit = False
    else:
        # Debit note (supplementary charge): Dr destination + Dr WHT; Cr revenue per line; Cr Output VAT.
        # Mirrors the Sales Invoice JE (revenue credited per line's account).
        dest_line = add(dest.id, f'{memo.memo_number} - {memo.customer_name}',
                        total, Decimal('0.00'))
        if wt_account is not None:
            add(wt_account.id, f'Creditable WHT: {memo.memo_number}', wht_total, Decimal('0.00'))
        for li in memo.line_items:
            if not li.account_id:
                continue
            net = Decimal(str(li.line_total or 0)) - Decimal(str(li.vat_amount or 0))
            if net <= 0:
                continue
            add(li.account_id, f'Additional charge: {memo.memo_number}', Decimal('0.00'), net)
        for vat_acct, vat_amt in output_vat_buckets(memo):
            if vat_amt <= 0:
                continue
            add(vat_acct.id, f'Output VAT: {memo.memo_number}', Decimal('0.00'), vat_amt)
            vat_bucket_total += vat_amt
        plug_is_debit = True

    # Header tie-out invariant on the non-plug legs (VAT already reconciled to header by
    # _output_vat_buckets; a mismatch is a bug, not a rounding residual).
    if vat_bucket_total != vat_total:
        raise ValueError('Output VAT legs do not tie to the memo VAT total.')

    # Absorb ONLY rounding residual into the destination (plug) leg.
    residual = (sum((l.debit_amount for l in lines), Decimal('0.00'))
                - sum((l.credit_amount for l in lines), Decimal('0.00')))
    if residual != Decimal('0.00'):
        if plug_is_debit:
            dest_line.debit_amount -= residual
        else:
            dest_line.credit_amount += residual

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f'{doc_label} JE is not balanced (debit={je.total_debit}, credit={je.total_credit}).')
    return je


def reverse_memo_je(memo, user_id, actor=None):
    """Post a reversing JE (swap debit/credit of the memo's JE) when a posted memo is voided.
    Returns the reversal JE, or None if the memo has no JE (a draft void). When ``actor`` is
    provided, also reverses whatever stock movements the memo posted (no-op if none) -- mirrors
    app.purchase_memos.je.reverse_purchase_memo_je. See R-03 slice 2a-v."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    src = memo.journal_entry
    if src is None:
        return None
    je = JournalEntry(
        entry_number=generate_entry_number(memo.branch_id),
        entry_date=ph_now().date(),
        description=f'Void Credit Memo {memo.memo_number} - {memo.customer_name}',
        reference=memo.memo_number, entry_type='reversal', branch_id=memo.branch_id,
        created_by_id=user_id, status='posted', posted_by_id=user_id, posted_at=ph_now(),
        is_balanced=False, total_debit=Decimal('0.00'), total_credit=Decimal('0.00'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for l in (JournalEntryLine.query.filter_by(entry_id=src.id)
              .order_by(JournalEntryLine.line_number).all()):
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=n, account_id=l.account_id,
            description=f'Reversal: {l.description}',
            debit_amount=l.credit_amount, credit_amount=l.debit_amount))
        n += 1
    db.session.flush()
    je.calculate_totals()
    if actor is not None:
        reverse_document_movements('sales_memo', memo.id, actor, journal_entry_id=je.id)
    return je
