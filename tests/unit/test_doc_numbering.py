"""Unit tests for the shared document-number generator (app/utils/doc_numbering.py).

The scope is a per-client setting read from AppSettings:
  'company' (the DEFAULT, and every existing client's behaviour) -- one series
            shared across all branches
  'branch'  -- each branch climbs its own series

Every document number column is a SINGLE-COLUMN GLOBAL unique index, so under
'branch' scope two branches must never produce the same string. See the
skip-forward rule pinned in the branch-scope tests below.
"""
from datetime import date

import pytest

# Module-level import so the model is registered before any db_session create_all().
from app.purchase_requests.models import PurchaseRequest  # noqa: F401
from app.settings import AppSettings

pytestmark = [pytest.mark.unit, pytest.mark.models]

COL = PurchaseRequest.pr_number


def _pr(db_session, number, branch_id=None, status='draft'):
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 8, 19),
                         status=status, branch_id=branch_id)
    db_session.add(pr)
    db_session.commit()
    return pr


def _scope(value):
    AppSettings.set_setting('document_number_scope', value)


# --------------------------------------------------------------------------
# company scope -- must reproduce today's behaviour EXACTLY
# --------------------------------------------------------------------------

def test_empty_table_returns_00001(db_session):
    from app.utils.doc_numbering import next_document_number
    assert next_document_number(PurchaseRequest, COL) == '00001'


def test_increments_from_the_global_max(db_session, main_branch, branch_manila):
    """Rows in TWO branches -- company scope draws from one shared pool."""
    from app.utils.doc_numbering import next_document_number
    _pr(db_session, '00006', branch_id=main_branch.id)
    _pr(db_session, '00007', branch_id=branch_manila.id)
    assert next_document_number(PurchaseRequest, COL) == '00008'


def test_continues_from_a_legacy_literal_number(db_session):
    from app.utils.doc_numbering import next_document_number
    _pr(db_session, '30500')
    assert next_document_number(PurchaseRequest, COL) == '30501'


def test_ignores_legacy_prefixed_numbers(db_session):
    from app.utils.doc_numbering import next_document_number
    _pr(db_session, 'PR-2026-07-0030')
    assert next_document_number(PurchaseRequest, COL) == '00001'


def test_default_when_key_absent_is_company(db_session, main_branch, branch_manila):
    """No AppSettings row at all -- the absence of the key is the safe state."""
    from app.utils.doc_numbering import next_document_number
    assert AppSettings.get_setting('document_number_scope') is None
    _pr(db_session, '00007', branch_id=main_branch.id)
    # branch_id supplied, but company scope must ignore it
    assert next_document_number(PurchaseRequest, COL, branch_manila.id) == '00008'


def test_unknown_scope_value_falls_back_to_company(db_session, main_branch, branch_manila):
    from app.utils.doc_numbering import next_document_number
    _scope('per-branch-oops')
    _pr(db_session, '00007', branch_id=main_branch.id)
    assert next_document_number(PurchaseRequest, COL, branch_manila.id) == '00008'


def test_filters_narrow_the_series_under_company_scope(db_session):
    """CONTROL for the `filters` argument -- applied under BOTH scopes.

    This is how the memo generators keep their per-memo_type series: memo_type
    is part of document identity, not a scope axis.
    """
    from app.utils.doc_numbering import next_document_number
    _pr(db_session, '00009', status='approved')
    assert next_document_number(
        PurchaseRequest, COL,
        filters=[PurchaseRequest.status == 'draft']) == '00001'
    assert next_document_number(PurchaseRequest, COL) == '00010'


# --------------------------------------------------------------------------
# branch scope
# --------------------------------------------------------------------------

def test_assigned_number_or_raise_returns_a_free_number(db_session):
    """CONTROL -- the guard must be transparent when there is no collision."""
    from app.utils.doc_numbering import assigned_number_or_raise
    assert assigned_number_or_raise(
        PurchaseRequest, COL, '00001', 'Quotation') == '00001'


def test_assigned_number_or_raise_rejects_a_taken_number(db_session):
    """The brand-new-branch case: no number field on the form, so a collision
    must surface as an actionable ValueError the view can flash, not an
    IntegrityError behind a generic 'An error occurred'."""
    from app.utils.doc_numbering import assigned_number_or_raise
    _pr(db_session, '00001')
    with pytest.raises(ValueError) as exc:
        assigned_number_or_raise(PurchaseRequest, COL, '00001', 'Quotation')
    assert '00001 is already in use' in str(exc.value)
    assert 'ask an administrator' in str(exc.value)


def test_branch_scope_gives_each_branch_its_own_series(db_session, main_branch,
                                                       branch_manila):
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00001', branch_id=main_branch.id)
    _pr(db_session, '00002', branch_id=main_branch.id)
    _pr(db_session, '50001', branch_id=branch_manila.id)
    assert next_document_number(PurchaseRequest, COL, main_branch.id) == '00003'
    assert next_document_number(PurchaseRequest, COL, branch_manila.id) == '50002'


def test_branch_scope_ignores_the_other_branchs_higher_number(db_session, main_branch,
                                                              branch_manila):
    """The defect itself: a far-higher number elsewhere must not drag this branch."""
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00007', branch_id=main_branch.id)
    _pr(db_session, '90000', branch_id=branch_manila.id)
    assert next_document_number(PurchaseRequest, COL, main_branch.id) == '00008'


def test_branch_with_no_prior_numeric_document_returns_00001(db_session, main_branch,
                                                             branch_manila):
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00042', branch_id=main_branch.id)
    assert next_document_number(PurchaseRequest, COL, branch_manila.id) == '00001'


def test_branch_placeholder_is_not_skipped_forward_even_when_taken(db_session, main_branch,
                                                                   branch_manila):
    """LOAD-BEARING. Starting a series is never guessed.

    '00001' is already held by the other branch, yet a branch with no series of
    its own STILL gets '00001' -- a placeholder the user types over. Skipping
    forward here would silently invent a starting number, which is a business
    decision the system must never make.
    """
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00001', branch_id=main_branch.id)
    assert next_document_number(PurchaseRequest, COL, branch_manila.id) == '00001'


def test_branch_scope_skips_a_globally_taken_candidate(db_session, main_branch,
                                                       branch_manila):
    """The mid-year flip: the two branches' maxima are adjacent, so the naive
    next value belongs to the other branch."""
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00598', branch_id=main_branch.id)
    _pr(db_session, '00599', branch_id=branch_manila.id)
    _pr(db_session, '00600', branch_id=branch_manila.id)
    assert next_document_number(PurchaseRequest, COL, main_branch.id) == '00601'


def test_branch_scope_skips_a_run_of_taken_candidates(db_session, main_branch,
                                                      branch_manila):
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00598', branch_id=main_branch.id)
    for n in ('00599', '00600', '00601', '00602', '00603'):
        _pr(db_session, n, branch_id=branch_manila.id)
    assert next_document_number(PurchaseRequest, COL, main_branch.id) == '00604'


def test_branch_scope_skips_a_number_held_by_a_null_branch_row(db_session, main_branch):
    """A legacy row with no branch is invisible to the branch series but still
    occupies the globally-unique number."""
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00007', branch_id=main_branch.id)
    _pr(db_session, '00008', branch_id=None)
    assert next_document_number(PurchaseRequest, COL, main_branch.id) == '00009'


def test_branch_scope_with_no_branch_id_falls_back_to_company_wide(db_session, main_branch,
                                                                   branch_manila):
    """No branch in hand -- use the shared series, never a NULL-branch one."""
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00006', branch_id=main_branch.id)
    _pr(db_session, '00007', branch_id=branch_manila.id)
    assert next_document_number(PurchaseRequest, COL) == '00008'


def test_branch_scope_narrows_by_filters_and_branch_together(db_session, main_branch,
                                                             branch_manila):
    from app.utils.doc_numbering import next_document_number
    _scope('branch')
    _pr(db_session, '00001', branch_id=main_branch.id, status='draft')
    _pr(db_session, '00050', branch_id=main_branch.id, status='approved')
    _pr(db_session, '00030', branch_id=branch_manila.id, status='draft')
    assert next_document_number(
        PurchaseRequest, COL, main_branch.id,
        filters=[PurchaseRequest.status == 'draft']) == '00002'


def test_company_scope_still_shares_one_series_across_branches(db_session, main_branch,
                                                               branch_manila):
    """CONTROL for every branch test above -- same data, company scope."""
    from app.utils.doc_numbering import next_document_number
    _scope('company')
    _pr(db_session, '00001', branch_id=main_branch.id)
    _pr(db_session, '00002', branch_id=main_branch.id)
    _pr(db_session, '50001', branch_id=branch_manila.id)
    assert next_document_number(PurchaseRequest, COL, main_branch.id) == '50002'
    assert next_document_number(PurchaseRequest, COL, branch_manila.id) == '50002'
