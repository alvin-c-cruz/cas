"""Display-only shaping of a posted journal entry for the pre-printed voucher face.

NOTHING HERE TOUCHES THE BOOKS. The posted journal entry is permanent (a posted
document is never edited; a correction is a reversing entry), so the merged rows
below are plain value objects, never ORM instances -- an ORM instance mutated for
display would be flushed to the database by the next commit in the request.
"""
from decimal import Decimal


class MergedJournalLine:
    """One printed row. Exposes exactly what the voucher templates read:
    `.account.code`, `.account.name`, `.debit_amount`, `.credit_amount`."""

    __slots__ = ('account', 'debit_amount', 'credit_amount', 'merged_count')

    def __init__(self, account, debit_amount, credit_amount, merged_count=1):
        self.account = account
        self.debit_amount = debit_amount
        self.credit_amount = credit_amount
        self.merged_count = merged_count

    def __repr__(self):
        return '<MergedJournalLine %s Dr %s Cr %s x%d>' % (
            getattr(self.account, 'code', None), self.debit_amount,
            self.credit_amount, self.merged_count)


def merge_same_account_lines(lines):
    """Sum legs that hit the same account ON THE SAME SIDE into one printed row.

    Owner, 2026-09-09: a voucher whose expenses all hit one account printed that
    account title once per source line, filling the JE face with repetition.

    PER SIDE, NEVER NETTED (the owner's decision). An account carrying both a
    debit and a credit keeps BOTH rows. Netting them would make the printed
    debit and credit totals disagree with the posted entry's totals, so the face
    would no longer tie to the books -- the one thing this face exists to show.
    Because merging only ever combines within a side, both totals are arithmetically
    unchanged, and an entry that tied before still ties after.

    ORDER is first-appearance: a merged row sits where its FIRST leg sat, so the
    caller's existing sort (non-VAT debits -> VAT debits -> credits, each by
    account code) survives untouched.

    A leg carrying both a debit and a credit is not merged at all -- it is not
    reachable through any posting path here, and silently splitting it across two
    rows would be a guess about an entry we do not understand.
    """
    out = []
    index = {}
    for line in lines:
        debit = Decimal(str(line.debit_amount or 0))
        credit = Decimal(str(line.credit_amount or 0))
        if debit > 0 and credit > 0:
            out.append(MergedJournalLine(line.account, line.debit_amount,
                                         line.credit_amount))
            continue
        side = 'D' if debit > 0 else 'C'
        key = (line.account_id, side)
        existing = index.get(key)
        if existing is None:
            row = MergedJournalLine(line.account, debit if side == 'D' else Decimal('0'),
                                    credit if side == 'C' else Decimal('0'))
            index[key] = row
            out.append(row)
        elif side == 'D':
            existing.debit_amount += debit
            existing.merged_count += 1
        else:
            existing.credit_amount += credit
            existing.merged_count += 1
    return out
