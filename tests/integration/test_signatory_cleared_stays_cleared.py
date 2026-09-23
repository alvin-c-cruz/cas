"""A signatory the user CLEARS must print blank, not come back from the company default.

Angilyn, via the owner, 2026-09-23: "she emptied the noted by field of PR and yet
the printout still has the name there."

THE COLLISION
-------------
Two halves of app/common/signatories.py disagreed about what an empty column
means, and each said so in its own docstring without noticing the other:

  * `assign()` -- "Blank stays blank -- an empty name prints an empty ruled line
    to sign by hand, which is a legitimate choice, not missing data to be
    back-filled from the company setting at save time." It stored None.
  * `for_print()` -- "a document predating this feature (all NULL) still prints
    the configured company names instead of three blank lines." It read None as
    "no opinion" and fell back to the company setting.

Both are reasonable. Together they mean a cleared name reappears on the paper.
NULL was doing two jobs: "never set, this document predates the feature" and
"deliberately emptied by a user", and nothing could tell them apart.

THE FIX
-------
Split the two meanings, no migration needed:
  * NULL   -> never set. The company default still prints (legacy rows).
  * ''     -> a user submitted this field empty. Print a blank line.

`assign()` now stores what was submitted, empty string and all; `for_print()`
falls back only on NULL.

Shared by Purchase Requisition and Receiving Report, so both are covered here.
"""
from datetime import date

import pytest

from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


def _company_defaults(prefix='pr', names=('Company Preparer', 'Company Noter',
                                         'Company Approver')):
    """Set the company-wide names these documents fall back to.

    Keys come from company_settings.views.get_signatories: '<prefix>_sig<slot>_name'
    over SIGNATORY_SLOTS -- NOT a guessed '_signatory_N_' shape, which silently sets
    nothing and makes a fallback test pass for the wrong reason.
    """
    from app.company_settings.views import SIGNATORY_SLOTS
    for slot, name in zip(SIGNATORY_SLOTS, names):
        AppSettings.set_setting(f'{prefix}_sig{slot}_name', name)


def _rr_vendor(db_session):
    """receiving_reports.vendor_id is NOT NULL, so a receipt needs one."""
    from app.vendors.models import Vendor
    v = Vendor.query.filter_by(code='SIG-V').first()
    if v is None:
        v = Vendor(code='SIG-V', name='Signatory Vendor')
        db_session.add(v); db_session.commit()
    return v


class TestForPrintDistinguishesNeverSetFromCleared:
    """Unit-level on the shared helper: the whole bug lives in these two lines."""

    class _Doc:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    def test_a_cleared_signatory_prints_blank(self, app, db_session):
        from app.common.signatories import for_print
        from app.purchase_requests.models import SIGNATORY_FIELDS, SIGNATORY_ROLES
        _company_defaults()
        db_session.commit()

        doc = self._Doc(prepared_by='Real Preparer', noted_by='', approved_by=None)

        out = dict((role, name) for role, name in
                   for_print(doc, SIGNATORY_FIELDS, SIGNATORY_ROLES, 'pr'))

        assert out[SIGNATORY_ROLES[1]] == '', \
            'a name the user deleted must not come back from the company setting'

    def test_a_never_set_signatory_still_falls_back(self, app, db_session):
        """The reason the fallback exists: requisitions saved before per-document
        signatories shipped have NULL columns and must still print the configured
        names rather than three blank lines."""
        from app.common.signatories import for_print
        from app.purchase_requests.models import SIGNATORY_FIELDS, SIGNATORY_ROLES
        _company_defaults()
        db_session.commit()

        doc = self._Doc(prepared_by=None, noted_by=None, approved_by=None)

        out = dict((role, name) for role, name in
                   for_print(doc, SIGNATORY_FIELDS, SIGNATORY_ROLES, 'pr'))

        assert out[SIGNATORY_ROLES[1]] == 'Company Noter'

    def test_a_document_naming_only_one_keeps_the_others_defaults(self, app, db_session):
        """Per-slot, not all-or-nothing -- the existing contract, unchanged."""
        from app.common.signatories import for_print
        from app.purchase_requests.models import SIGNATORY_FIELDS, SIGNATORY_ROLES
        _company_defaults()
        db_session.commit()

        doc = self._Doc(prepared_by=None, noted_by='Angilyn M', approved_by=None)

        out = dict((role, name) for role, name in
                   for_print(doc, SIGNATORY_FIELDS, SIGNATORY_ROLES, 'pr'))

        assert out[SIGNATORY_ROLES[0]] == 'Company Preparer'
        assert out[SIGNATORY_ROLES[1]] == 'Angilyn M'


class TestAssignRecordsTheUsersIntent:
    """The save half. Storing None for a submitted-empty field is what made the
    two meanings indistinguishable."""

    class _Form:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, type('F', (), {'data': v})())

    def test_an_emptied_field_is_stored_as_empty_not_null(self, app):
        from app.common.signatories import assign
        from app.purchase_requests.models import SIGNATORY_FIELDS

        doc = type('D', (), {})()
        form = self._Form(prepared_by='A', noted_by='', approved_by='C')

        assign(doc, form, SIGNATORY_FIELDS)

        assert doc.noted_by == '', 'a submitted-empty field is a decision, not absence'
        assert doc.noted_by is not None

    def test_whitespace_only_counts_as_emptied(self, app):
        from app.common.signatories import assign
        from app.purchase_requests.models import SIGNATORY_FIELDS

        doc = type('D', (), {})()
        form = self._Form(prepared_by='A', noted_by='   ', approved_by='C')

        assign(doc, form, SIGNATORY_FIELDS)

        assert doc.noted_by == ''

    def test_a_typed_name_is_stored_stripped(self, app):
        from app.common.signatories import assign
        from app.purchase_requests.models import SIGNATORY_FIELDS

        doc = type('D', (), {})()
        form = self._Form(prepared_by='  Angilyn M  ', noted_by='B', approved_by='C')

        assign(doc, form, SIGNATORY_FIELDS)

        assert doc.prepared_by == 'Angilyn M'


class TestEndToEndOnTheRequisitionPrintout:
    """Angilyn's actual report, through the real route."""

    def _login(self, client, user, branch):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = branch.id

    def _enable(self, db_session):
        from app.utils.cache_helpers import clear_module_config_cache
        for k in ('products', 'purchase_orders', 'purchase_requests'):
            AppSettings.set_setting(f'module_enabled:{k}', '1')
        db_session.commit()
        clear_module_config_cache()

    def test_a_cleared_noted_by_does_not_reappear_on_the_printout(
            self, client, db_session, admin_user, main_branch):
        from app.purchase_requests.models import PurchaseRequest
        self._enable(db_session)
        _company_defaults()
        pr = PurchaseRequest(pr_number='SIG-CLEAR', request_date=date(2026, 9, 23),
                             branch_id=main_branch.id, status='submitted',
                             created_by_id=admin_user.id,
                             prepared_by='Angilyn M', noted_by='', approved_by='')
        db_session.add(pr); db_session.commit()
        self._login(client, admin_user, main_branch)

        body = client.get(f'/purchase-requests/{pr.id}/print').data.decode()

        assert 'Angilyn M' in body, 'the name she DID enter must still print'
        assert 'Company Noter' not in body, \
            'the name she deleted came back from the company setting'

    def test_a_legacy_requisition_still_prints_the_company_names(
            self, client, db_session, admin_user, main_branch):
        """The behaviour the fallback exists for, which must survive the fix."""
        from app.purchase_requests.models import PurchaseRequest
        self._enable(db_session)
        _company_defaults()
        pr = PurchaseRequest(pr_number='SIG-LEGACY', request_date=date(2026, 9, 23),
                             branch_id=main_branch.id, status='submitted',
                             created_by_id=admin_user.id)
        db_session.add(pr); db_session.commit()
        self._login(client, admin_user, main_branch)

        body = client.get(f'/purchase-requests/{pr.id}/print').data.decode()

        assert 'Company Noter' in body


class TestTheReceivingReportSharesTheFix:
    """Same helper, same bug, so the receipt printout gets it too."""

    def test_a_cleared_signatory_prints_blank_on_an_rr(self, app, db_session):
        from app.common.signatories import for_print
        from app.receiving_reports.models import SIGNATORY_FIELDS, SIGNATORY_ROLES
        _company_defaults('rr', ('Company RR Preparer', 'Company RR Noter',
                                 'Company RR Approver'))
        db_session.commit()

        doc = type('D', (), {})()
        for f in SIGNATORY_FIELDS:
            setattr(doc, f, None)
        setattr(doc, SIGNATORY_FIELDS[1], '')

        out = [name for _role, name in
               for_print(doc, SIGNATORY_FIELDS, SIGNATORY_ROLES, 'rr')]

        assert out[1] == ''


class TestADeliberateBlankCarriesForwardAsBlank:
    """Follow-up, 2026-09-23. RECEIVING REPORTS ONLY -- see the note below.

    A receipt seeds its signatories from the encoder's last one, falling back to
    the company default per slot (owner, 2026-09-10: "signatories should autofill
    based on what the user encoded last time"). That fallback read a blank slot as
    "nothing to carry", so a receiver who deliberately emptied a name got the
    company name back on the next receipt and had to clear it again every time.

    With '' now meaning "deliberately emptied", the carry-forward can tell the two
    apart exactly as the printout can:
        previous is None -> that receipt never set it   -> company default
        previous is ''   -> the user emptied it         -> stay empty
        previous is name -> carry the name

    PURCHASE REQUISITIONS DO NOT DO THIS. They call prefill_form(), which always
    seeds from the company setting and has no concept of a last document, so a
    cleared name there returns on every new requisition. Giving PR the same
    carry-forward RR got is a separate decision and is NOT made here.
    """

    class _Field:
        def __init__(self, data=''):
            self.data = data

    class _Form:
        def __init__(self, fields):
            for f in fields:
                setattr(self, f, TestADeliberateBlankCarriesForwardAsBlank._Field())

    def _fields_roles(self):
        from app.receiving_reports.models import SIGNATORY_FIELDS, SIGNATORY_ROLES
        return SIGNATORY_FIELDS, SIGNATORY_ROLES

    def test_an_emptied_slot_stays_empty_on_the_next_receipt(self, app, db_session,
                                                             main_branch, admin_user):
        from app.common.signatories import prefill_form_from_last
        from app.receiving_reports.models import ReceivingReport
        fields, roles = self._fields_roles()
        _company_defaults('rr', ('RR Prep', 'RR Note', 'RR Appr'))
        v = _rr_vendor(db_session)
        last = ReceivingReport(rr_number='SIG-FWD-1', receipt_date=date(2026, 9, 23),
                               branch_id=main_branch.id, status='draft',
                               vendor_id=v.id, vendor_name=v.name,
                               created_by_id=admin_user.id)
        for f in fields:
            setattr(last, f, 'Someone')
        setattr(last, fields[1], '')          # deliberately emptied
        db_session.add(last); db_session.commit()

        form = self._Form(fields)
        prefill_form_from_last(form, fields, 'rr', roles, ReceivingReport, admin_user.id)

        assert getattr(form, fields[1]).data == '', \
            'a slot the user emptied must not be refilled from the company setting'
        assert getattr(form, fields[0]).data == 'Someone'

    def test_a_slot_the_last_receipt_never_set_still_takes_the_default(
            self, app, db_session, main_branch, admin_user):
        from app.common.signatories import prefill_form_from_last
        from app.receiving_reports.models import ReceivingReport
        fields, roles = self._fields_roles()
        _company_defaults('rr', ('RR Prep', 'RR Note', 'RR Appr'))
        v = _rr_vendor(db_session)
        last = ReceivingReport(rr_number='SIG-FWD-2', receipt_date=date(2026, 9, 23),
                               branch_id=main_branch.id, status='draft',
                               vendor_id=v.id, vendor_name=v.name,
                               created_by_id=admin_user.id)
        for f in fields:
            setattr(last, f, None)            # never set -- a legacy receipt
        db_session.add(last); db_session.commit()

        form = self._Form(fields)
        prefill_form_from_last(form, fields, 'rr', roles, ReceivingReport, admin_user.id)

        assert getattr(form, fields[1]).data == 'RR Note'

    def test_a_first_ever_receipt_takes_the_defaults(self, app, db_session, admin_user):
        from app.common.signatories import prefill_form_from_last
        from app.receiving_reports.models import ReceivingReport
        fields, roles = self._fields_roles()
        _company_defaults('rr', ('RR Prep', 'RR Note', 'RR Appr'))
        db_session.commit()

        form = self._Form(fields)
        prefill_form_from_last(form, fields, 'rr', roles, ReceivingReport, admin_user.id)

        assert getattr(form, fields[1]).data == 'RR Note'

    def test_what_the_user_already_typed_is_never_overwritten(
            self, app, db_session, main_branch, admin_user):
        """Unchanged contract: a re-render after a validation failure must keep
        what they entered."""
        from app.common.signatories import prefill_form_from_last
        from app.receiving_reports.models import ReceivingReport
        fields, roles = self._fields_roles()
        _company_defaults('rr', ('RR Prep', 'RR Note', 'RR Appr'))
        db_session.commit()

        form = self._Form(fields)
        getattr(form, fields[1]).data = 'Typed By Hand'
        prefill_form_from_last(form, fields, 'rr', roles, ReceivingReport, admin_user.id)

        assert getattr(form, fields[1]).data == 'Typed By Hand'
