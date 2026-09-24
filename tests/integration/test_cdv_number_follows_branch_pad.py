"""A new CV's suggested number continues the BRANCH's own pad.

Owner, 2026-09-24: "the CV number should increment based on what the user entered
before ... See SO for corp and extra." Philgen's CVs are pre-printed pads numbered
like '01644' and '1656', typed off the paper; the form used to suggest
'CD-YYYY-MM-NNNN', a shape the client never uses, so every entry meant retyping.

The series is PER BRANCH, as SO numbering is (CORP plain, EXTRA with its 'E'), not
per encoder as the PO pad is -- the owner's choice. The digit part increments as a
NUMBER while the zero-padding and any trailing marker survive verbatim, exactly as
next_po_number_for() does. It is only ever a suggestion: cdv_number stays typed,
editable and unique.
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.branches.models import Branch
from app.cash_disbursements.models import CashDisbursementVoucher
from tests.integration.test_cdv_number_editable import login, setup_accounts, make_vendor

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


@pytest.fixture
def pad(db_session):
    """(vendor, cash account) plus a `put(number, branch)` that records a CV."""
    _ap, _wt, cash, _exp = setup_accounts(db_session)
    vendor = make_vendor(db_session)

    def put(number, branch):
        cdv = CashDisbursementVoucher(
            branch_id=branch.id, cdv_number=number, cdv_date=date(2026, 9, 24),
            vendor_id=vendor.id, vendor_name=vendor.name, payment_method='cash',
            cash_account_id=cash.id, status='draft', total_amount=Decimal('1'))
        db_session.add(cdv); db_session.commit()
        return cdv
    return put


@pytest.fixture
def extra(db_session):
    b = Branch(code='EXTRA', name='Extra Branch', is_active=True)
    db_session.add(b); db_session.commit()
    return b


def _next(branch):
    from app.cash_disbursements.views import next_cdv_number_for
    return next_cdv_number_for(branch.id)


class TestTheSeries:

    def test_no_prior_cv_falls_back_to_the_generated_shape(self, db_session, main_branch, pad):
        """A first-ever entry has nothing to continue from; the demo/RIC shape stays."""
        assert re.fullmatch(r'CD-\d{4}-\d{2}-0001', _next(main_branch))

    def test_increments_the_last_number_keeping_its_width(self, db_session, main_branch, pad):
        pad('01644', main_branch)
        assert _next(main_branch) == '01645'

    def test_the_numeric_max_wins_not_the_latest_string(self, db_session, main_branch, pad):
        """Philgen's real data: '01644' and '1656' on one pad. 1656 is the higher
        number even though '01644' sorts after it as text."""
        pad('1656', main_branch)
        pad('01644', main_branch)
        assert _next(main_branch) == '1657'

    def test_a_trailing_marker_survives(self, db_session, extra, pad):
        pad('0009E', extra)
        assert _next(extra) == '0010E'

    def test_width_grows_on_overflow(self, db_session, main_branch, pad):
        pad('9999', main_branch)
        assert _next(main_branch) == '10000'

    def test_each_branch_continues_its_own_pad(self, db_session, main_branch, extra, pad):
        """CORP and EXTRA are separate pads, as they are for SO."""
        pad('0100', main_branch)
        pad('0005', extra)
        assert _next(extra) == '0006'
        assert _next(main_branch) == '0101'

    def test_legacy_generated_numbers_do_not_perturb_the_pad(self, db_session, main_branch, pad):
        pad('CD-2026-08-0007', main_branch)
        pad('0042', main_branch)
        assert _next(main_branch) == '0043'

    def test_only_legacy_numbers_means_fallback(self, db_session, main_branch, pad):
        pad('CD-2026-08-0007', main_branch)
        assert re.fullmatch(r'CD-\d{4}-\d{2}-\d{4}', _next(main_branch))

    def test_never_suggests_a_number_already_in_use(self, db_session, main_branch, extra, pad):
        """cdv_number is unique company-wide. If the other branch already holds the
        next number, walk THIS branch's series past it rather than offer a save
        that will be refused -- the PO pad's collision lesson."""
        pad('0002', main_branch)
        pad('0003', extra)
        assert _next(main_branch) == '0004'


def test_the_create_form_opens_on_the_branch_pads_next_number(client, db_session, admin_user,
                                                              main_branch, pad):
    pad('01644', main_branch)
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    html = client.get('/cash-disbursements/create').get_data(as_text=True)
    m = re.search(r'<input[^>]*name="cdv_number"[^>]*value="([^"]*)"', html)
    assert m, 'cdv_number input not rendered'
    assert m.group(1) == '01645'
