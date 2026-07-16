"""BUG-REQUIRED-ASTERISK-FIELD-MISALIGN: the required-field asterisk must render
INSIDE the <label> element, not as a trailing sibling after it.

Root cause: `.form-label` is `display:block`; a `<span class="required">*</span>`
rendered as a sibling AFTER `</label>` wraps onto its own phantom line (the label
already terminated its block-level line), adding ~21px of unwanted vertical space
-- visible whenever a required field shares a `.form-row-2` with an optional field
that has no such phantom line. Fix: hand-write the label markup so the asterisk
span shares the label's own line. Assert the FIXED shape renders (asterisk inside
the label, not a sibling after it) across all 4 affected templates.
"""
import pytest

pytestmark = [pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def _assert_asterisk_inside_label(html, field_label_text, field_id):
    """The fixed markup shape: <label ... for="{id}">{text}<span class="required" ...>*</span></label>
    -- i.e. the label's own closing tag comes AFTER the asterisk span, not before it."""
    needle = f'>{field_label_text}<span class="required"'
    assert needle in html, (
        f'Expected asterisk INSIDE the label for {field_id!r} '
        f'(looking for {needle!r}) -- markup shape regressed to the trailing-sibling bug.'
    )
    # The old buggy shape closed the label BEFORE the span (`</label><span class="required"`).
    # Confirm that shape no longer appears for this field's label.
    old_shape = f'for="{field_id}">{field_label_text}</label><span class="required"'
    assert old_shape not in html, f'Found the OLD buggy trailing-sibling shape for {field_id!r}'


class TestRequiredAsteriskInsideLabel:
    def test_account_create_form(self, client, db_session, accountant_user, main_branch):
        login(client)
        resp = client.get('/accounts/create')
        assert resp.status_code == 200
        html = resp.data.decode()
        _assert_asterisk_inside_label(html, 'Account Code', 'code')
        _assert_asterisk_inside_label(html, 'Account Name', 'name')
        _assert_asterisk_inside_label(html, 'Account Type', 'account_type')

    def test_vat_category_create_form(self, client, db_session, admin_user, main_branch):
        # VAT-category maintenance is full-access-only (admin/Chief Accountant);
        # an accountant cannot reach this route at all.
        login(client, username='admin', password='admin123')
        resp = client.get('/vat-categories/create')
        assert resp.status_code == 200
        html = resp.data.decode()
        _assert_asterisk_inside_label(html, 'VAT Rate (%)', 'rate')

    def test_sales_vat_category_create_form(self, client, db_session, admin_user, main_branch):
        login(client, username='admin', password='admin123')
        resp = client.get('/sales-vat-categories/create')
        assert resp.status_code == 200
        html = resp.data.decode()
        _assert_asterisk_inside_label(html, 'VAT Rate (%)', 'rate')
        _assert_asterisk_inside_label(html, 'Transaction Nature', 'transaction_nature')

    def test_withholding_tax_create_form(self, client, db_session, admin_user, main_branch):
        login(client, username='admin', password='admin123')
        resp = client.get('/withholding-tax/create')
        assert resp.status_code == 200
        html = resp.data.decode()
        _assert_asterisk_inside_label(html, 'WT Rate (%)', 'rate')
