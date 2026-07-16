"""Vendor Debit Memo journal-entry builder -- the buy-side inverse mirror of
``app/sales_memos/je.py``'s credit-memo branch.

A Vendor Debit Memo (our return of goods to a vendor) REVERSES the returned
portion of the referenced posted Accounts Payable bill:
    Dr  {AP-Trade (control account) | cash account | Vendor Credits}  destination (= gross - WHT)
    Dr  Withholding Tax Payable (control account)     WHT unwound (if wht > 0)
      Cr  Purchase Returns & Allowances (contra-expense)  net purchase reversed (subtotal - VAT)
      Cr  Input VAT (per input-VAT-account bucket)          VAT reversed

AP-Trade and WHT-Payable are resolved via ``app.posting.control_accounts.
get_control_account`` (settings-assigned). Purchase Returns and Vendor Credits are
resolved via ``app.purchase_memos.service.resolve_memo_account`` (settings-assigned
via AppSettings, NOT a control_accounts entry -- Task 2's verified finding: sales
resolves its mirror accounts, sales_returns_allowances/customer_credits_advances,
the same way). Neither is hardcoded -- see BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS.

Divergence from the credit-memo mirror (documented, not a guess): the sales
credit-memo branch's destination leg sits on the CREDIT side (AR is an asset;
crediting it reduces what the customer owes), so its residual/plug math is
``dest_line.credit_amount += residual``. Our destination leg sits on the DEBIT
side (AP-Trade is a liability; debiting it reduces what we owe the vendor), which
is structurally the sales *debit-note* branch's plug shape
(``dest_line.debit_amount -= residual``) even though the leg SET (destination +
WHT debited; contra + VAT credited) mirrors the credit-memo branch. This is the
"clone-and-invert" the task brief calls for, not a divergent reimplementation.

Follows the posted-JE-leg-vs-header invariant: the non-plug legs equal the memo
header buckets by construction; the destination is the reconciled residual (only
sub-centavo VAT-bucket rounding ever lands there).
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

    if memo.memo_type != 'debit':
        raise ValueError(f'Unknown memo_type {memo.memo_type!r}.')

    subtotal = Decimal(str(memo.subtotal or 0))    # VAT-inclusive line sum (mirrors AP)
    vat_total = Decimal(str(memo.vat_amount or 0))
    wht_total = Decimal(str(memo.withholding_tax_amount or 0))
    total = Decimal(str(memo.total_amount or 0))
    net_purchase = subtotal - vat_total

    # Destination account.
    if memo.destination == 'ap':
        dest = get_control_account('ap_trade')
    elif memo.destination == 'cash_refund':
        dest = memo.cash_account
        if dest is None:
            raise ValueError('No cash account selected.')
    else:  # vendor_credit
        dest = service.resolve_memo_account(service.VENDOR_CREDITS_KEY, 'Vendor Credits')

    wt_account = get_control_account('wht_payable') if wht_total > 0 else None

    je_status = 'posted' if memo.status == 'posted' else 'draft'
    je = JournalEntry(
        entry_number=generate_entry_number(memo.branch_id),
        entry_date=memo.memo_date,
        description=f'Debit Memo {memo.memo_number} - {memo.vendor_name}',
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

    # Dr destination (= gross - WHT) + Dr WHT unwound; Cr Purchase Returns + Cr Input VAT.
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

    # Header tie-out invariant on the non-plug legs (VAT already reconciled to
    # header by input_vat_buckets; a mismatch is a bug, not a rounding residual).
    if vat_bucket_total != vat_total:
        raise ValueError('Input VAT legs do not tie to the memo VAT total.')

    # Absorb ONLY rounding residual into the destination (plug) leg -- destination
    # sits on the DEBIT side here (see module docstring divergence note).
    residual = (sum((l.debit_amount for l in lines), Decimal('0.00'))
                - sum((l.credit_amount for l in lines), Decimal('0.00')))
    if residual != Decimal('0.00'):
        dest_line.debit_amount -= residual

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f'Debit Memo JE is not balanced (debit={je.total_debit}, credit={je.total_credit}).')

    if memo.destination == 'ap':
        bill = memo.accounts_payable
        bill.amount_paid = Decimal(str(bill.amount_paid or 0)) + total
        bill.balance = Decimal(str(bill.total_amount)) - bill.amount_paid

    return je
