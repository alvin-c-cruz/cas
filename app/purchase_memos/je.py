"""Vendor Debit Memo / Vendor Credit Memo journal-entry builder.

A Vendor DEBIT Memo (our return of goods to a vendor, memo_type='debit') REVERSES
the returned portion of the referenced posted Accounts Payable bill:
    Dr  {AP-Trade (control account) | cash account | Vendor Credits}  destination (= gross - WHT)
    Dr  Withholding Tax Payable (control account)     WHT unwound (if wht > 0)
      Cr  Purchase Returns & Allowances (contra-expense)  net purchase reversed (subtotal - VAT)
      Cr  Input VAT (per input-VAT-account bucket)          VAT reversed

A Vendor CREDIT Memo (a supplementary vendor charge, memo_type='credit') is the
buy-side mirror of the sales-side Debit Note -- it INCREASES what we owe the
vendor:
    Dr  {line's expense/purchase account}, per line     net (subtotal - VAT)
    Dr  Input VAT (per input-VAT-account bucket)         VAT on the charge
      Cr  Withholding Tax Payable (control account)        WHT withheld (if wht > 0)
      Cr  {AP-Trade (control account) | cash account | Vendor Credits}  destination (= gross - WHT)

AP-Trade and WHT-Payable are resolved via ``app.posting.control_accounts.
get_control_account`` (settings-assigned). Purchase Returns (debit-memo only) and
Vendor Credits (both types) are resolved via ``app.purchase_memos.service.
resolve_memo_account`` (settings-assigned via AppSettings, NOT a control_accounts
entry). Neither is hardcoded -- see BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS.

Destination-account RESOLUTION is shared, uniform code across both memo types
(mirrors app/sales_memos/je.py) -- only the debit/credit SIDE the destination and
WHT legs land on differs by memo_type. This is why the 'vendor_credit'
destination needs no special-casing: crediting the Vendor Credits ASSET account
(credit memo) correctly DECREASES it (drawing down an existing credit to fund the
new charge), while debiting it (debit memo) correctly INCREASES it (a return adds
to the credit) -- same account-resolution code, opposite natural-balance effect,
by construction.

Follows the posted-JE-leg-vs-header invariant: the non-plug legs equal the memo
header buckets by construction; the destination is the reconciled residual (only
sub-centavo VAT-bucket rounding ever lands there).

Adjudication 1 (Task 4 of the original Vendor Debit Memo build, binding, unchanged
by the credit-memo addition): this module builds the JE ONLY -- it does NOT
mutate the referenced AP bill's balance. That mirrors sales_memos/je.py::
post_memo_je. The AP-balance mutation for EITHER memo type lives in
app/purchase_memos/views.py (_apply_memo_to_ap/_reverse_memo_from_ap for debit,
_apply_credit_to_ap/_reverse_credit_from_ap for credit), called from the shared
_post_impl/_void_impl.
"""
from decimal import Decimal

from app import db
from app.utils import ph_now
from app.journal_entries.utils import generate_entry_number
from app.purchase_memos import service
from app.posting.purchase_vat import input_vat_buckets
from app.posting.control_accounts import get_control_account


def post_purchase_memo_je(memo, user_id):
    """Build and return the memo's JournalEntry (draft or posted, matching memo.status)."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    if memo.memo_type not in ('debit', 'credit'):
        raise ValueError(f'Unknown memo_type {memo.memo_type!r}.')

    subtotal = Decimal(str(memo.subtotal or 0))    # VAT-inclusive line sum (mirrors AP)
    vat_total = Decimal(str(memo.vat_amount or 0))
    wht_total = Decimal(str(memo.withholding_tax_amount or 0))
    total = Decimal(str(memo.total_amount or 0))
    net_purchase = subtotal - vat_total

    # Destination account (shared by both memo types).
    if memo.destination == 'ap':
        dest = get_control_account('ap_trade')
    elif memo.destination == 'cash_refund':
        dest = memo.cash_account
        if dest is None:
            raise ValueError('No cash account selected.')
    else:  # vendor_credit
        dest = service.resolve_memo_account(service.VENDOR_CREDITS_KEY, 'Vendor Credits')

    wt_account = get_control_account('wht_payable') if wht_total > 0 else None

    doc_label = 'Debit Memo' if memo.memo_type == 'debit' else 'Credit Memo'
    je_status = 'posted' if memo.status == 'posted' else 'draft'
    je = JournalEntry(
        entry_number=generate_entry_number(memo.branch_id),
        entry_date=memo.memo_date,
        description=f'{doc_label} {memo.memo_number} - {memo.vendor_name}',
        reference=memo.memo_number, entry_type='purchase', branch_id=memo.branch_id,
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

    if memo.memo_type == 'debit':
        # Reverse the returned portion: Dr destination + Dr WHT; Cr Purchase Returns + Cr Input VAT.
        dest_line = add(dest.id, f'{memo.memo_number} - {memo.vendor_name}',
                        total, Decimal('0.00'))
        if wt_account is not None:
            add(wt_account.id, f'Withholding Tax Payable unwound: {memo.memo_number}',
                wht_total, Decimal('0.00'))
        contra = service.resolve_memo_account(service.PURCHASE_RETURNS_KEY,
                                              'Purchase Returns & Allowances')
        if net_purchase > 0:
            add(contra.id, f'Purchase Returns: {memo.memo_number}', Decimal('0.00'), net_purchase)
        for vat_acct, vat_amt in input_vat_buckets(memo):
            if vat_amt <= 0:
                continue
            add(vat_acct.id, f'Input VAT reversed: {memo.memo_number}', Decimal('0.00'), vat_amt)
            vat_bucket_total += vat_amt
        plug_is_debit = True
    else:
        # Supplementary charge (mirrors the Sales Invoice/Debit Note JE): Dr destination +
        # Dr WHT; Cr per-line expense/purchase account; Cr Input VAT.
        dest_line = add(dest.id, f'{memo.memo_number} - {memo.vendor_name}',
                        Decimal('0.00'), total)
        if wt_account is not None:
            add(wt_account.id, f'Withholding Tax Payable: {memo.memo_number}',
                Decimal('0.00'), wht_total)
        for li in memo.line_items:
            if not li.account_id:
                continue
            net = Decimal(str(li.line_total or 0)) - Decimal(str(li.vat_amount or 0))
            if net <= 0:
                continue
            add(li.account_id, f'Additional charge: {memo.memo_number}', net, Decimal('0.00'))
        for vat_acct, vat_amt in input_vat_buckets(memo):
            if vat_amt <= 0:
                continue
            add(vat_acct.id, f'Input VAT: {memo.memo_number}', vat_amt, Decimal('0.00'))
            vat_bucket_total += vat_amt
        plug_is_debit = False

    # Header tie-out invariant on the non-plug legs (VAT already reconciled to
    # header by input_vat_buckets; a mismatch is a bug, not a rounding residual).
    if vat_bucket_total != vat_total:
        raise ValueError('Input VAT legs do not tie to the memo VAT total.')

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


def reverse_purchase_memo_je(memo, user_id):
    """Post a reversing JE (swap debit/credit of the memo's JE) when a posted memo is voided.
    Returns the reversal JE, or None if the memo has no JE (a draft void). Mirror of
    sales_memos.je.reverse_memo_je. Type-agnostic -- works identically for either
    memo_type since it just swaps whatever legs the original JE has."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    src = memo.journal_entry
    if src is None:
        return None
    doc_label = 'Debit Memo' if memo.memo_type == 'debit' else 'Credit Memo'
    je = JournalEntry(
        entry_number=generate_entry_number(memo.branch_id),
        entry_date=ph_now().date(),
        description=f'Void {doc_label} {memo.memo_number} - {memo.vendor_name}',
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
    return je
