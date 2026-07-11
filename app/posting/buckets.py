"""Per-account tax-bucket allocation for journal-entry posting.

Two behaviour-preserving primitives extracted from the six historical
``_*_buckets`` routines (AP input-VAT / AP WHT / SI output-VAT / CDV input-VAT /
CDV WHT / CRV output-VAT) as R4 Phase 1 of the CAS application-review
remediation.

The six routines are deliberately **not identical** -- their variant axes
(reconcile trigger, largest-bucket tie-break, negative guard, empty-bucket
fallback, non-positive-line skip, zero-amount test) are passed in as parameters
here rather than harmonised. Each caller keeps its exact prior behaviour by
supplying its own variant params; harmonising any axis would be a behaviour
change, not a refactor. The variant matrix lives in the plan
``cas-review-remediation.md`` (R4).

Extracting the reconciliation tail matters most: the largest-bucket absorption
is exactly where R1's CRV/AP WHT-override money bugs lived. Centralising it
gives one place to test and one coupling point to reason about.
"""
from decimal import Decimal

_ZERO = Decimal('0.00')


def group_tax_buckets(lines, *, amount_of, account_of, amount_predicate,
                      on_missing_account, line_skip=None):
    """Sum each line's tax amount into a per-account bucket.

    Returns an ordered list of ``(Account, Decimal)`` pairs sorted by account
    code -- pre-reconciliation. Parameters (all keyword-only) capture the
    per-document variation:

    - ``lines``:            iterable of document line rows.
    - ``line_skip(line)``:  optional predicate; when it returns ``True`` the line
                            is skipped entirely (drops non-positive Section-B
                            lines for CDV/CRV). ``None`` never skips (AP/SI).
    - ``amount_of(line)``:  the line's tax amount; any falsy value counts as 0.
    - ``amount_predicate(amt)``: return ``True`` to include this line's amount.
                            Callers pass ``amt > 0`` (AP/SI) or ``amt != 0``
                            (CDV/CRV) to match their prior zero test.
    - ``account_of(line)``: resolve the destination ``Account`` or ``None`` when
                            the line has no configured account.
    - ``on_missing_account``: either the literal string ``'skip'`` (drop a line
                            whose account resolves to ``None`` -- the WHT
                            routines, which have already folded in their
                            fallback) or a ``callable(line) -> str`` returning
                            the ``ValueError`` message to raise (the VAT
                            routines, whose category must have a tax account).
    """
    buckets = {}  # account_id -> [Account, Decimal]
    for line in lines:
        if line_skip is not None and line_skip(line):
            continue
        amt = Decimal(str(amount_of(line) or 0))
        if not amount_predicate(amt):
            continue
        acct = account_of(line)
        if acct is None:
            if on_missing_account == 'skip':
                continue
            raise ValueError(on_missing_account(line))
        if acct.id not in buckets:
            buckets[acct.id] = [acct, _ZERO]
        buckets[acct.id][1] += amt
    return [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]


def reconcile_buckets_to_total(buckets, header_total, *, only_if=True,
                               largest_by='amount', fallback_account=None,
                               allow_negative=False, negative_error=None,
                               empty_error=None):
    """Reconcile an ordered bucket list to ``header_total``, then drop zeros.

    Behaviour-preserving extraction of the six routines' shared tail. Given the
    ordered ``(Account, Decimal)`` list from :func:`group_tax_buckets`, absorb
    the difference between the buckets' sum and the document header total into a
    single bucket, so the booked legs tie to the header (the fix R1 made for CRV
    and AP). Parameters (all keyword-only) capture the per-document variation:

    - ``only_if``:          when ``False`` the reconciliation is skipped entirely
                            (no active override on this document); the negative
                            guard and the zero-drop still run. AP/SI VAT and AP
                            WHT pass ``True`` (always reconcile to the header);
                            CDV/CRV pass their ``*_override`` flag.
    - ``largest_by``:       ``'amount'`` absorbs the diff into the bucket with the
                            largest signed amount (AP/SI); ``'abs'`` uses the
                            largest absolute value (the sign-aware CDV/CRV
                            variant, whose buckets may be negative).
    - ``fallback_account``: when the diff is non-zero but there are no buckets,
                            book the whole diff to this account (the WHT
                            pure-override case). ``None`` means no fallback.
    - ``allow_negative``:   when ``False``, raise ``negative_error`` if any bucket
                            ends up negative (the overshoot guard). CDV/CRV VAT
                            pass ``True`` (sign-aware; no guard).
    - ``negative_error`` / ``empty_error``: the ``ValueError`` messages. Each
                            document supplies its exact prior wording.
                            ``empty_error`` is raised only when there is a
                            non-zero diff, no buckets, and no fallback (WHT); VAT
                            routines leave it ``None`` so that case is a silent
                            no-op, matching their ``and ordered`` short-circuit.
    """
    ordered = list(buckets)
    if only_if:
        total = sum((amt for _, amt in ordered), _ZERO)
        diff = Decimal(str(header_total)) - total
        if diff != _ZERO:
            if ordered:
                if largest_by == 'abs':
                    key = lambda b: abs(b[1])  # noqa: E731 - local tie-break key
                else:
                    key = lambda b: b[1]       # noqa: E731 - local tie-break key
                largest_id = max(ordered, key=key)[0].id
                ordered = [
                    (acct, amt + diff if acct.id == largest_id else amt)
                    for acct, amt in ordered
                ]
            elif fallback_account is not None:
                ordered = [(fallback_account, diff)]
            elif empty_error is not None:
                raise ValueError(empty_error)
            # else: non-zero diff, no buckets, no fallback, no error message ->
            # silent no-op (the VAT routines' `if ... and ordered` short-circuit)
    if not allow_negative and any(amt < _ZERO for _, amt in ordered):
        raise ValueError(negative_error)
    return [(acct, amt) for acct, amt in ordered if amt != _ZERO]
