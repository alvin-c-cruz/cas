"""The APV pre-printed voucher renders its particulars band, gated by lineItems.enabled.

Reverses the 2026-07-07 "intentionally NOT rendered" decision. The gate exists because
PhilGen is live on this form with a saved layout whose JE face sits at y=272 -- a band at
the default y=300 would print straight through it.
"""
import pytest

from app.settings import AppSettings
from tests.integration.test_apv_print_form import login, _posted_apv

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


def _render(client, db_session, main_branch, ap, *, enabled, columns=None):
    """Store a layout, then GET the pre-printed print page and return its HTML."""
    from app.accounts_payable.preprinted_layout import save_layout, get_layout
    AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
    layout = get_layout(main_branch.id)
    layout['lineItems']['enabled'] = enabled
    for key, patch in (columns or {}).items():
        col = next(c for c in layout['lineItems']['columns'] if c['key'] == key)
        col.update(patch)
    save_layout(layout, 'admin', main_branch.id)
    login(client)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return client.get(f'/accounts-payable/{ap.id}/print').data.decode()


def _apv_with_three_lines(db_session, main_branch):
    """Same shape as `_posted_apv`, but with three line items (1..3) instead of one."""
    from decimal import Decimal
    from datetime import date
    from app.vendors.models import Vendor
    from app.accounts.models import Account
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    vendor = Vendor(code='PPV3', name='Preprint Supplier Three Inc.', tin='111-222-333-001',
                    is_active=True)
    db_session.add(vendor); db_session.commit()
    expense = Account(code='5010', name='Office Supplies', account_type='Expense',
                      normal_balance='debit', is_active=True)
    db_session.add(expense); db_session.commit()
    ap = AccountsPayable(ap_number='APV-PP-3', ap_date=date(2026, 7, 7),
                         due_date=date(2026, 8, 6), vendor_id=vendor.id,
                         vendor_name=vendor.name, vendor_tin=vendor.tin,
                         vendor_invoice_number='SUP-INV-10', branch_id=main_branch.id,
                         status='posted', subtotal=Decimal('33600'),
                         vat_amount=Decimal('3600'), total_before_wt=Decimal('33600'),
                         withholding_tax_amount=Decimal('600'),
                         total_amount=Decimal('33000'))
    for n in (1, 2, 3):
        ap.line_items.append(AccountsPayableItem(line_number=n, description=f'Bond paper {n}',
                                                  quantity=Decimal('10'), unit_price=Decimal('1120'),
                                                  line_total=Decimal('11200'),
                                                  account_id=expense.id))
    db_session.add(ap); db_session.commit()
    return ap


class TestBandGate:
    def test_band_absent_when_disabled(self, client, db_session, admin_user, main_branch):
        """A legacy layout (no `enabled` key) prints no band."""
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=False)
        assert 'data-el="lineItems"' not in html
        # NOT `'class="pp-col' not in html` (the brief's original assertion): the
        # designer chrome unconditionally emits `id="ppColControls" class="pp-col-controls
        # screen-only"` (a substring collision with `pp-col`), which false-failed this
        # control test before any implementation existed. `data-col="` is unique to a
        # per-column band div and appears nowhere else in the rendered page.
        assert 'data-col="' not in html

    def test_band_present_when_enabled(self, client, db_session, admin_user, main_branch):
        """CONTROL. Without this the absence assertion above passes vacuously."""
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        assert 'data-el="lineItems"' in html
        assert 'data-col="line_number"' in html


class TestColumnVisibility:
    def test_hidden_column_carries_pp_col_hidden(self, client, db_session, admin_user,
                                                 main_branch):
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True,
                       columns={'account_code': {'visible': False}})
        assert 'data-col="account_code"' in html          # still emitted...
        marker = html.split('data-col="account_code"')[0].rsplit('<div', 1)[1]
        assert 'pp-col-hidden' in marker                  # ...but hidden

    def test_visible_column_has_no_hidden_class(self, client, db_session, admin_user,
                                                main_branch):
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True,
                       columns={'account_code': {'visible': True}})
        marker = html.split('data-col="account_code"')[0].rsplit('<div', 1)[1]
        assert 'pp-col-hidden' not in marker


class TestAccountSplitRendering:
    def test_code_and_name_render_in_separate_columns(self, client, db_session, admin_user,
                                                      main_branch):
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        assert 'data-col="account_code"' in html
        assert 'data-col="account_name"' in html
        assert '5010' in html and 'Office Supplies' in html

    def test_the_concatenated_form_is_gone(self, client, db_session, admin_user, main_branch):
        """The standard print emits `code : name` in one cell; the band must not.

        _posted_apv's account is code 5010 / name 'Office Supplies'.
        """
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        assert '5010 : Office Supplies' not in html


class TestAlignmentInvariant:
    def test_every_column_emits_one_cell_per_line_item(self, client, db_session, admin_user,
                                                       main_branch):
        """Equal-length stacks are what keep columns registered against the paper boxes."""
        ap = _apv_with_three_lines(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        for key in ('line_number', 'description', 'amount', 'account_code', 'account_name'):
            # Slice from this column's marker to the start of the next column div.
            block = html.split(f'data-col="{key}"')[1].split('<div class="pp-col')[0]
            assert block.count('class="pp-cell"') == 3, f'{key} emitted != 3 cells'


class TestJEFaceUntouched:
    def test_je_face_still_renders_at_its_saved_coordinates(self, client, db_session,
                                                            admin_user, main_branch):
        """CONTROL: the band must not disturb the JE face clients have positioned.

        Sets the JE face's saved position to PhilGen's real live coordinates
        (x=75, y=272 -- see this file's module docstring) BEFORE enabling the band,
        then asserts the rendered `data-je="combined"` element's inline style still
        carries that exact `left:`/`top:`. If the band ever shoved the JE face to a
        different position (e.g. its own default y=300), this fails.
        """
        from app.accounts_payable.preprinted_layout import save_layout, get_layout
        from tests.integration.test_apv_print_form import _apv_with_je
        AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
        layout = get_layout(main_branch.id)
        layout['journalEntry']['combined']['x'] = 75
        layout['journalEntry']['combined']['y'] = 272
        save_layout(layout, 'admin', main_branch.id)

        ap = _apv_with_je(db_session, main_branch, balanced=True)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        # The JE face renders from its own saved coords, untouched by the band.
        assert 'data-je="combined"' in html
        tag = html.split('data-je="combined"')[1].split('>')[0].replace(' ', '')
        assert 'left:75px' in tag
        assert 'top:272px' in tag
