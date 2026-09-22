"""The Sales Order Notes box must not be covered by the signatories row.

Owner report 2026-09-22 on live SO 00001E: "does not allow editing of notes",
on /edit and then on /amend. Confirmed in the live browser, and it was NOT a
validation problem -- the Update button was enabled, the textarea was present,
enabled, not readonly, fully opaque and carrying its stored text.

`document.elementFromPoint()` over the middle of the Notes box returned the
`checked_by` input. Both header blocks carry `grid-area: notes`:

    transactions.css      .notes-col { grid-area: notes; ... }
    sales_orders/form.html  <div class="notes-col ...">  <- Notes
                            <div class="notes-col ...">  <- signatories

so they stacked in the one named area at identical geometry (measured: both
846,281 983x269), and the signatories, later in the DOM, painted over the Notes
box and took every click aimed at it. The field stayed keyboard-reachable, which
is why it looked fine and why no server-side test could see it.

The signatories row now has its own grid area, opted into by a modifier so the
five other forms sharing that stylesheet keep their three-area grid.

WHAT THESE TESTS CAN AND CANNOT DO
----------------------------------
They pin the STRUCTURE that made the overlap possible: exactly one element in
the `notes` area, the signatories in their own, and the modifier present to give
that area a row. They cannot measure the rendered geometry -- only a browser can,
and the check that catches a regression here is elementFromPoint over the Notes
box, not a screenshot: an overlay of exactly the same size is invisible by eye.
"""
import re

import pytest
from datetime import date
from decimal import Decimal

from app.sales_orders.models import SalesOrder, SalesOrderItem

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if b is None:
        b = Branch(code='CORP', name='CORP')
        db_session.add(b); db_session.commit()
    return b


@pytest.fixture
def customer(db_session):
    return _customer(db_session)


@pytest.fixture
def logged_in(client, db_session, admin_user, branch):
    _login(client, admin_user)
    _select_branch(client, branch.id)
    return admin_user


def _so(db_session, branch, customer, status='draft', number='COV-1'):
    so = SalesOrder(branch_id=branch.id, so_number=number,
                    order_date=date(2026, 9, 22), status=status,
                    customer_id=customer.id, customer_name=customer.name,
                    payment_terms='Net 60', notes='NOTE')
    so.line_items.append(SalesOrderItem(line_number=1, quantity=Decimal('1'),
                                        unit_price=Decimal('1.00'),
                                        amount=Decimal('1.00')))
    db_session.add(so); db_session.commit()
    return so


def _grid_area_classes(html):
    """Every class list inside the header grid that claims a named grid area."""
    return re.findall(r'class="((?:notes-col|signatories-col|left-col-fields|right-col)[^"]*)"',
                      html)


class TestOnlyOneBlockClaimsTheNotesArea:

    @pytest.mark.parametrize('path', ['create', 'edit'])
    def test_the_form_renders_exactly_one_notes_col(
            self, client, db_session, branch, customer, logged_in, path):
        so = _so(db_session, branch, customer, number='COV-%s' % path)
        url = '/sales-orders/create' if path == 'create' \
            else f'/sales-orders/{so.id}/edit'
        html = client.get(url).data.decode()
        notes_cols = [c for c in _grid_area_classes(html) if c.startswith('notes-col')]
        assert len(notes_cols) == 1, \
            'two elements in `grid-area: notes` stack and the later one covers ' \
            'the Notes box: %r' % notes_cols

    def test_the_amend_form_renders_exactly_one_notes_col(
            self, client, db_session, branch, customer, logged_in):
        """The screen the owner actually reported."""
        so = _so(db_session, branch, customer, status='confirmed', number='COV-AM')
        html = client.get(f'/sales-orders/{so.id}/amend').data.decode()
        notes_cols = [c for c in _grid_area_classes(html) if c.startswith('notes-col')]
        assert len(notes_cols) == 1

    def test_the_signatories_have_their_own_area(
            self, client, db_session, branch, customer, logged_in):
        so = _so(db_session, branch, customer, number='COV-SIG')
        html = client.get(f'/sales-orders/{so.id}/edit').data.decode()
        assert 'class="signatories-col' in html
        # The applied attribute, not the bare class name: the stylesheet link and
        # any inline CSS would otherwise satisfy a substring check.
        assert 'prepared_by' in html and 'checked_by' in html

    def test_the_grid_opts_into_the_signatories_row(
            self, client, db_session, branch, customer, logged_in):
        """Without the modifier the new area has no row to sit in, and the
        browser drops the element back on top of the others."""
        so = _so(db_session, branch, customer, number='COV-MOD')
        html = client.get(f'/sales-orders/{so.id}/edit').data.decode()
        assert 'class="form-main-grid form-main-grid--signatories"' in html


class TestTheStylesheetDefinesWhatTheFormAsksFor:
    """The template names three hooks that live in a SHARED stylesheet. If that
    file is edited without them, the layout silently collapses back."""

    def test_the_modifier_and_area_exist(self):
        css = open('app/static/transactions.css', encoding='utf-8').read()
        assert '.form-main-grid--signatories' in css
        assert '.signatories-col' in css
        assert 'signatories signatories' in css, \
            'the modifier must give the signatories area an actual row'

    def test_the_narrow_viewport_grid_also_names_the_row(self):
        """Otherwise the overlap comes back at tablet width only -- the hardest
        kind of regression to notice."""
        css = open('app/static/transactions.css', encoding='utf-8').read()
        tablet = css[css.index('@media (max-width: 1023px)'):]
        assert '"signatories"' in tablet

    def test_notes_col_still_owns_the_notes_area_alone(self):
        css = open('app/static/transactions.css', encoding='utf-8').read()
        assert css.count('grid-area: notes;') == 1


class TestTheStylesheetIsNotServedFromCache:
    """A CSS-only fix that every browser already has cached is not a fix. The
    version must move with the file."""

    def test_every_page_loading_it_asks_for_the_same_new_version(self):
        import glob
        refs = []
        for path in glob.glob('app/**/templates/**/*.html', recursive=True):
            html = open(path, encoding='utf-8').read()
            refs += re.findall(r"transactions\.css'\s*\)\s*\}\}\?v=(\d+)", html)
        assert refs, 'no template loads transactions.css -- did the path change?'
        assert len(set(refs)) == 1, \
            'templates disagree about the stylesheet version: %s' % sorted(set(refs))
        assert int(refs[0]) >= 5, \
            'the version must be bumped past 4, or browsers keep the cached copy ' \
            'that still stacks the two blocks'
