"""Credit/Debit memo journal-entry builder.

Phase 1: credit memo only. A credit memo REVERSES the returned portion of the SI:
    Dr  Sales Returns & Allowances (contra-revenue)   net revenue reversed (subtotal - VAT)
    Dr  Output VAT (per output-VAT-account bucket)     VAT reversed
      Cr  Creditable WHT Receivable (10212)              WHT unwound
      Cr  {AR 10201 | cash account | Customer Credits}   destination (= gross - WHT)

Follows the posted-JE-leg-vs-header invariant: the non-plug legs equal the memo header
buckets by construction; the destination is the reconciled residual (only sub-centavo
VAT-bucket rounding ever lands there).
"""
from decimal import Decimal

from app import db
from app.utils import ph_now
from app.journal_entries.utils import generate_entry_number
from app.accounts.models import Account
from app.sales_memos import service
from app.posting.sales_vat import output_vat_buckets


def _account_by_code(code, label):
    a = Account.query.filter_by(code=code).first()
    if a is None:
        raise ValueError(f'{label} ({code}) not found in the Chart of Accounts.')
    return a


def post_memo_je(memo, user_id):
    """Build and return the memo's JournalEntry (draft or posted, matching memo.status)."""
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
        dest = _account_by_code('10201', 'Accounts Receivable - Trade')
    elif memo.destination == 'cash_refund':
        dest = memo.cash_account
        if dest is None:
            raise ValueError('No cash account selected.')
    else:  # customer_credit
        dest = service.resolve_memo_account(service.CUSTOMER_CREDITS_KEY, 'Customer Credits/Advances')

    wt_account = _account_by_code('10212', 'Creditable Withholding Tax') if wht_total > 0 else None

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


def reverse_memo_je(memo, user_id):
    """Post a reversing JE (swap debit/credit of the memo's JE) when a posted memo is voided.
    Returns the reversal JE, or None if the memo has no JE (a draft void)."""
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
    return je
