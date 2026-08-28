"""The SO's signatory slots agree across model, form and print roles.

Behaviour -- storing, trimming, clearing, carrying forward, printing -- is owned
by test_so_signatory_fields.py and test_so_print_signatory_roles.py, and this
file deliberately does NOT repeat it: two files asserting the same thing drift,
and the four-slot change of 2026-08-28 had to edit both of those already.

What is NOT covered there, and is the whole point here, is that the three
enumerations stay the same length and the same order. They are separate lists in
separate modules:

  * SalesOrder.SIGNATORY_FIELDS / SIGNATORY_ROLES  (models.py)
  * SalesOrderForm.SIGNATORY_FIELDS                (forms.py)
  * a StringField per slot                         (forms.py)
  * a db.Column per slot                           (models.py)

A slot added to one and missed in another does not crash. It prints a caption
over the wrong name, or offers an input that never persists, or adds a column
nobody can fill -- which is exactly the failure mode a fourth slot introduces.
"""
import pytest

from app.sales_orders.forms import SalesOrderForm
from app.sales_orders.models import (SIGNATORY_FIELDS, SIGNATORY_ROLES,
                                     SalesOrder, next_so_signatories_for)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

#: Owner request 2026-08-28 -- Prepared / Checked / Noted / Approved, in the
#: order they are signed, which is the order they print.
EXPECTED = ('prepared_by', 'checked_by', 'noted_by', 'approved_by')
EXPECTED_ROLES = ('Prepared by', 'Checked by', 'Noted by', 'Approved by')


def test_the_slots_are_the_four_in_signing_order():
    assert SIGNATORY_FIELDS == EXPECTED


def test_roles_line_up_with_fields_one_for_one():
    """`zip(FIELDS, ROLES)` is what pairs a caption with a name. Unequal
    lengths do not raise -- zip just drops the tail, silently printing fewer
    blocks than the form collects."""
    assert SIGNATORY_ROLES == EXPECTED_ROLES
    assert len(SIGNATORY_ROLES) == len(SIGNATORY_FIELDS)


def test_the_form_agrees_with_the_model():
    assert SalesOrderForm.SIGNATORY_FIELDS == SIGNATORY_FIELDS


@pytest.mark.parametrize('slot', EXPECTED)
def test_every_slot_has_an_input(slot):
    """A column with no input is unfillable."""
    assert hasattr(SalesOrderForm, slot), 'no form field for %r' % slot


@pytest.mark.parametrize('slot', EXPECTED)
def test_every_slot_has_a_column(slot):
    """An input with no column silently discards what the user typed."""
    assert slot in {c.name for c in SalesOrder.__table__.columns}


def test_carry_forward_covers_every_slot(db_session, main_branch, admin_user):
    """next_so_signatories_for builds its dict FROM SIGNATORY_FIELDS, so a new
    slot is carried automatically -- pinned because a hand-listed dict here
    would be a fifth enumeration to drift."""
    carried = next_so_signatories_for(admin_user.id)
    assert set(carried) == set(EXPECTED)
    assert carried == {f: '' for f in EXPECTED}, (
        'a user with no prior order must get blanks, never placeholders')
