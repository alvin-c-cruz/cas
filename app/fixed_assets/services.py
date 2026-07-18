"""Tagging eligibility, cancel-time guard queries, and shared creation path for
the Fixed Asset register (R-05 Slice 1). This is the ONLY place that knows how
to read a taggable line off AP/CDV/JV -- AP/CDV/JV views import from here rather
than reimplementing the eligibility rules."""
from app import db
from app.fixed_assets.models import FixedAsset
from app.accounts.models import Account


class FixedAssetTagError(ValueError):
    """Raised when a document line is not eligible to be tagged as a fixed asset."""


def get_taggable_line(source_type, source_id, source_line_id):
    """Fetch and validate a posted AP-bill/CDV/JV line for tagging.

    Returns (line, cost_account_id, amount). Raises FixedAssetTagError if the
    line doesn't exist, its document isn't posted, it's already tagged, or (JV
    only) it isn't a debit line.
    """
    if get_tag_for_line(source_type, source_id, source_line_id) is not None:
        raise FixedAssetTagError('This line is already tagged as a fixed asset.')

    if source_type == 'ap_bill':
        from app.accounts_payable.models import AccountsPayableItem
        line = db.session.get(AccountsPayableItem, source_line_id)
        if line is None or line.ap_id != source_id:
            raise FixedAssetTagError('AP line not found.')
        if line.ap.status != 'posted':
            raise FixedAssetTagError('Only posted AP bill lines can be capitalized.')
        return line, line.account_id, line.amount

    if source_type == 'cdv':
        from app.cash_disbursements.models import CDVExpenseLine
        line = db.session.get(CDVExpenseLine, source_line_id)
        if line is None or line.cdv_id != source_id:
            raise FixedAssetTagError('CDV line not found.')
        if line.cdv.status != 'posted':
            raise FixedAssetTagError('Only posted CDV lines can be capitalized.')
        return line, line.account_id, line.amount

    if source_type == 'jv':
        from app.journal_entries.models import JournalEntryLine
        line = db.session.get(JournalEntryLine, source_line_id)
        if line is None or line.entry_id != source_id:
            raise FixedAssetTagError('JV line not found.')
        if line.entry.status != 'posted':
            raise FixedAssetTagError('Only posted JV lines can be capitalized.')
        if not line.debit_amount or line.debit_amount <= 0:
            raise FixedAssetTagError('Only debit JV lines can be capitalized.')
        return line, line.account_id, line.debit_amount

    raise FixedAssetTagError(f'Unknown acquisition source type: {source_type}')


def get_tag_for_line(source_type, source_id, source_line_id):
    """The FixedAsset already tagging this line, or None. Opening assets have
    no source line, so they never match."""
    if source_type == 'opening' or source_line_id is None:
        return None
    return FixedAsset.query.filter_by(
        acquisition_source_type=source_type,
        acquisition_source_id=source_id,
        acquisition_source_line_id=source_line_id,
    ).first()


def get_tags_for_document(source_type, source_id):
    """All FixedAsset rows tagging any line of this document -- used by the
    AP/CDV/JV cancel() guard to block reversing a document that backs an asset."""
    return FixedAsset.query.filter_by(
        acquisition_source_type=source_type,
        acquisition_source_id=source_id,
    ).order_by(FixedAsset.id).all()


def leaf_accounts_by_type(account_type):
    """Active leaf (postable) accounts of a given account_type, code-sorted.
    'Leaf' means it has a parent (not top-level) AND no other active account
    has it as a parent -- mirrors the is_header computation in
    app/accounts/views.py: a node is a PARENT (non-postable) if it is
    top-level (no parent_id) OR has children; otherwise it is a LEAF."""
    all_active = Account.query.filter_by(is_active=True).all()
    parent_ids = {a.parent_id for a in all_active if a.parent_id}
    return sorted(
        (
            a for a in all_active
            if a.account_type == account_type
            and a.parent_id is not None
            and a.id not in parent_ids
        ),
        key=lambda a: a.code,
    )


def create_fixed_asset(**kwargs):
    """Shared creation path for both the tag flow and the opening-asset flow.
    Callers pass every FixedAsset column as a kwarg; this function just
    constructs, adds, and commits -- callers own audit logging."""
    asset = FixedAsset(**kwargs)
    db.session.add(asset)
    db.session.commit()
    return asset
