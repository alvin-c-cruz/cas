"""The suggested PO number must be one the buyer can actually save.

Second half of BUG-PO-CREATE-DROPS-LINES-ON-VALIDATION-REJECT. `next_po_number_for`
suggests off each purchaser's OWN pad, documenting its premise: "the two pads'
number ranges NEVER overlap". PhilGen's live data breaks that premise -- four
orders, all plain numeric, one branch, no pad markers -- so measured on
2026-08-30 the form handed two of the three users a number already in use:

    admin     own pad 00001,00005   ->  00006   free
    angilyn   own pad 00002,00003   ->  00004   COLLIDES (alvin's)
    alvin     own pad 00004         ->  00005   COLLIDES

Deterministic, not intermittent: the purchaser was refused on every single
attempt, which is why retrying never helped her.

The repair keeps the pad design -- the suggestion still walks HER series, and
width and pad marker are still preserved -- and only declines to offer a number
that is already taken. It stays a SUGGESTION either way: po_number is typed off
the paper form and remains user-editable.
"""
import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, next_po_number_for

pytestmark = [pytest.mark.unit, pytest.mark.purchase_orders]


def _po(branch, number, user_id=None):
    po = PurchaseOrder(branch_id=branch.id, po_number=number,
                       vendor_name='Acme', created_by_id=user_id)
    db.session.add(po)
    db.session.commit()
    return po


class TestItNeverSuggestsATakenNumber:

    def test_it_skips_a_number_another_purchaser_already_used(
            self, db_session, main_branch, admin_user):
        """THE REPRODUCTION, in the shape the live data actually had: her own pad
        ends at 00003, but 00004 belongs to someone else."""
        _po(main_branch, '00002', admin_user.id)
        _po(main_branch, '00003', admin_user.id)
        _po(main_branch, '00004', None)          # the other purchaser's

        assert next_po_number_for(admin_user.id, main_branch.id) == '00005'

    def test_it_skips_a_whole_run_of_taken_numbers(
            self, db_session, main_branch, admin_user):
        """One step forward is not enough -- the other pad may hold several."""
        _po(main_branch, '00002', admin_user.id)
        for n in ('00003', '00004', '00005'):
            _po(main_branch, n, None)

        assert next_po_number_for(admin_user.id, main_branch.id) == '00006'

    def test_it_preserves_the_pad_marker_while_skipping(
            self, db_session, main_branch, admin_user):
        """The marker is what distinguishes the two physical pads; skipping a
        collision must not quietly drop it and move her onto the other pad."""
        _po(main_branch, '00001E', admin_user.id)
        _po(main_branch, '00002E', None)

        assert next_po_number_for(admin_user.id, main_branch.id) == '00003E'

    def test_it_preserves_zero_padded_width_while_skipping(
            self, db_session, main_branch, admin_user):
        _po(main_branch, '007', admin_user.id)
        _po(main_branch, '008', None)

        assert next_po_number_for(admin_user.id, main_branch.id) == '009'


class TestTheControls:

    def test_an_uncontested_pad_is_not_skipped_forward(
            self, db_session, main_branch, admin_user):
        """CONTROL. Skipping happens ONLY on a collision. If the fix simply added
        one more every time, this is what would catch it -- and the purchaser
        would find her series growing gaps for no reason."""
        _po(main_branch, '00002', admin_user.id)

        assert next_po_number_for(admin_user.id, main_branch.id) == '00003'

    def test_a_purchaser_with_no_pad_still_falls_back(
            self, db_session, main_branch, admin_user):
        """CONTROL. Her first ever order has no series to infer from, and the
        company-wide generator answers -- unchanged by this fix."""
        _po(main_branch, '00009', None)

        assert next_po_number_for(admin_user.id, main_branch.id) == '00010'

    def test_the_suggestion_is_always_free(
            self, db_session, main_branch, admin_user):
        """CONTROL, stated as the property the whole fix exists to guarantee,
        rather than as another worked example."""
        _po(main_branch, '00002', admin_user.id)
        for n in ('00003', '00004', '00005', '00006'):
            _po(main_branch, n, None)

        suggestion = next_po_number_for(admin_user.id, main_branch.id)

        taken = {p.po_number for p in PurchaseOrder.query.all()}
        assert suggestion not in taken, \
            'the form suggested a number the save will refuse'
