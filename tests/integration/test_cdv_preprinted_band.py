"""The CDV pre-printed voucher renders its Section B (Direct Expenses) band, gated by
lineItems.enabled. Reverses the 2026-07-07 "intentionally NOT rendered" decision."""
import pytest

from app.settings import AppSettings
from tests.integration.test_cdv_print_form import login, _cdv_with_je

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def _render(client, db_session, main_branch, cdv, *, enabled, columns=None):
    """Store a layout, then GET the pre-printed print page and return its HTML."""
    from app.cash_disbursements.preprinted_layout import save_layout, get_layout
    AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
    layout = get_layout(main_branch.id)
    layout['lineItems']['enabled'] = enabled
    for key, patch in (columns or {}).items():
        col = next(c for c in layout['lineItems']['columns'] if c['key'] == key)
        col.update(patch)
    save_layout(layout, 'admin', main_branch.id)
    login(client)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return client.get(f'/cash-disbursements/{cdv.id}/print').data.decode()


def _cdv_with_three_lines(db_session, main_branch):
    """Same shape as `_cdv_with_je`, but with three expense lines (1..3) instead of one."""
    from decimal import Decimal
    from datetime import date
    from app.vendors.models import Vendor
    from app.accounts.models import Account
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine

    vendor = Vendor(code='CDV3', name='Three Line Payee Inc.', tin='222-333-444-000',
                    is_active=True)
    db_session.add(vendor); db_session.commit()
    expense = Account(code='5040', name='Repairs and Maintenance', account_type='Expense',
                      normal_balance='debit', is_active=True)
    db_session.add(expense); db_session.commit()
    cash = Account(code='1010', name='Cash in Bank', account_type='Asset',
                   normal_balance='debit', is_active=True)
    db_session.add(cash); db_session.commit()

    cdv = CashDisbursementVoucher(branch_id=main_branch.id, cdv_number='CDV-PP-3',
                                  cdv_date=date(2026, 7, 7), vendor_id=vendor.id,
                                  vendor_name=vendor.name, vendor_tin=vendor.tin,
                                  payment_method='check', check_number='CHK-003',
                                  cash_account_id=cash.id, status='posted',
                                  total_expense=Decimal('3000'), total_amount=Decimal('3000'))
    for n in (1, 2, 3):
        cdv.expense_lines.append(CDVExpenseLine(line_number=n, description=f'Repair item {n}',
                                                 quantity=Decimal('1'), unit_price=Decimal('1000'),
                                                 line_total=Decimal('1000'), amount=Decimal('1000'),
                                                 account_id=expense.id))
    db_session.add(cdv); db_session.commit()
    return cdv


class TestBandGate:
    def test_band_absent_when_disabled(self, client, db_session, admin_user, main_branch):
        """A legacy layout (no `enabled` key) prints no band."""
        cdv = _cdv_with_je(db_session, main_branch)
        html = _render(client, db_session, main_branch, cdv, enabled=False)
        assert 'data-el="lineItems"' not in html
        # `data-col="` is unique to a per-column band div; the designer chrome's
        # `class="pp-col-controls"` would substring-match a `'class="pp-col'` probe, so
        # use the `data-col=` marker instead (per the APV sibling's fix).
        assert 'data-col="' not in html

    def test_band_present_when_enabled(self, client, db_session, admin_user, main_branch):
        """CONTROL. Without this the absence assertion above passes vacuously."""
        cdv = _cdv_with_je(db_session, main_branch)
        html = _render(client, db_session, main_branch, cdv, enabled=True)
        assert 'data-el="lineItems"' in html
        assert 'data-col="line_number"' in html


class TestColumnVisibility:
    def test_hidden_column_carries_pp_col_hidden(self, client, db_session, admin_user,
                                                 main_branch):
        cdv = _cdv_with_je(db_session, main_branch)
        html = _render(client, db_session, main_branch, cdv, enabled=True,
                       columns={'account_code': {'visible': False}})
        assert 'data-col="account_code"' in html          # still emitted...
        marker = html.split('data-col="account_code"')[0].rsplit('<div', 1)[1]
        assert 'pp-col-hidden' in marker                  # ...but hidden

    def test_visible_column_has_no_hidden_class(self, client, db_session, admin_user,
                                                main_branch):
        cdv = _cdv_with_je(db_session, main_branch)
        html = _render(client, db_session, main_branch, cdv, enabled=True,
                       columns={'account_code': {'visible': True}})
        marker = html.split('data-col="account_code"')[0].rsplit('<div', 1)[1]
        assert 'pp-col-hidden' not in marker


class TestAccountSplitRendering:
    def test_code_and_name_render_in_separate_columns(self, client, db_session, admin_user,
                                                      main_branch):
        cdv = _cdv_with_je(db_session, main_branch)
        html = _render(client, db_session, main_branch, cdv, enabled=True)
        assert 'data-col="account_code"' in html
        assert 'data-col="account_name"' in html
        assert '5030' in html and 'Utilities Expense' in html

    def test_the_concatenated_form_is_gone(self, client, db_session, admin_user, main_branch):
        """The standard print emits `code : name` in one cell; the band must not.

        `_cdv_with_je`'s expense account is code 5030 / name 'Utilities Expense'.
        """
        cdv = _cdv_with_je(db_session, main_branch)
        html = _render(client, db_session, main_branch, cdv, enabled=True)
        assert '5030 : Utilities Expense' not in html


class TestAlignmentInvariant:
    def test_every_column_emits_one_cell_per_line_item(self, client, db_session, admin_user,
                                                       main_branch):
        """Equal-length stacks are what keep columns registered against the paper boxes."""
        cdv = _cdv_with_three_lines(db_session, main_branch)
        html = _render(client, db_session, main_branch, cdv, enabled=True)
        for key in ('line_number', 'description', 'amount', 'account_code', 'account_name'):
            # Slice from this column's marker to the start of the next column div.
            block = html.split(f'data-col="{key}"')[1].split('<div class="pp-col')[0]
            assert block.count('class="pp-cell"') == 3, f'{key} emitted != 3 cells'


class TestJEFaceUntouched:
    def test_je_face_still_renders_at_its_saved_coordinates(self, client, db_session,
                                                            admin_user, main_branch):
        """CONTROL: the band must not disturb the JE face clients have positioned.

        Sets the JE face's saved position to an arbitrary coordinate BEFORE enabling the
        band, then asserts the rendered `data-je="combined"` element's inline style still
        carries that exact `left:`/`top:`. If the band ever shoved the JE face to a
        different position (e.g. its own default y), this fails.
        """
        from app.cash_disbursements.preprinted_layout import save_layout, get_layout
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        layout = get_layout(main_branch.id)
        layout['journalEntry']['combined']['x'] = 75
        layout['journalEntry']['combined']['y'] = 272
        save_layout(layout, 'admin', main_branch.id)

        cdv = _cdv_with_je(db_session, main_branch, balanced=True)
        html = _render(client, db_session, main_branch, cdv, enabled=True)
        # The JE face renders from its own saved coords, untouched by the band.
        assert 'data-je="combined"' in html
        tag = html.split('data-je="combined"')[1].split('>')[0].replace(' ', '')
        assert 'left:75px' in tag
        assert 'top:272px' in tag
