"""The CDV pre-printed voucher can print the vendor's Check Payee Name.

Owner, 2026-09-06: "I have set Johnson's Check Payee Name to test it. It needs to be
visible on the CDV itself ... both vendor name and Check Payee Name should be visible."

`Vendor.check_payee_name` has existed for a long time, with the comment "for printing on
checks" -- it is captured on the vendor form, shown on the vendor detail page, and
reached NO printed document at all. This puts it on the voucher, ALONGSIDE Pay To rather
than instead of it. The two names differ only RARELY (owner, 2026-09-06) -- but when they
do, a voucher showing one name and a cheque showing another cannot be reconciled, so both
have to be on the page.

TWO deliberate decisions are pinned here, because both would otherwise look like bugs:

1. It ships HIDDEN. A new field appearing unbidden at a default position would print text
   where a client's pre-printed pad has none -- possibly over an existing box -- on every
   CDV instance at once. Same opt-in discipline as lineItems.enabled.

2. It reads LIVE from the vendor, while `vendor_name` beside it is a snapshot on the CDV.
   So a payee name edited after posting changes what a reprint shows. Raised with the
   owner as a possible BIR-permanence gap and SETTLED: the check payee name is not
   material to a BIR examination, and a payee differing from the vendor name is rare to
   begin with. Snapshotting would cost a column plus a migration on every client instance
   to protect something an examiner does not look at. Recorded so the next reader does not
   reopen it as a bug.
"""
import pytest

from app.settings import AppSettings
from tests.integration.test_cdv_print_form import login, _cdv_with_je

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def _open_tag(html, needle):
    start = html.rindex('<div', 0, html.index(needle))
    return html[start:html.index('>', start) + 1]


def _render(client, db_session, main_branch, payee=None, show=False):
    """Set the vendor's check payee name, optionally unhide the field, render."""
    from app.cash_disbursements.preprinted_layout import get_layout, save_layout
    cdv = _cdv_with_je(db_session, main_branch)
    if payee is not None:
        cdv.vendor.check_payee_name = payee
        db_session.commit()
    lay = get_layout(main_branch.id)
    lay['fields']['check_payee']['hidden'] = not show
    save_layout(lay, 'admin', main_branch.id)
    db_session.commit()
    AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/cash-disbursements/%s/print' % cdv.id)
    assert resp.status_code == 200, resp.headers.get('Location')
    return resp.get_data(as_text=True), cdv


class TestTheFieldExists:

    def test_it_is_a_field_key(self):
        from app.cash_disbursements.preprinted_layout import FIELD_KEYS
        assert 'check_payee' in FIELD_KEYS

    def test_it_has_a_label(self):
        """The label is what the designer's Fields strip shows -- without it the checkbox
        is unnamed and the field cannot be found to unhide."""
        from app.cash_disbursements.preprinted_layout import FIELD_LABELS
        assert FIELD_LABELS['check_payee'] == 'Check Payee'

    def test_it_sits_beside_pay_to_not_instead_of_it(self):
        """THE owner's requirement: both names visible. A layout where one replaced the
        other would satisfy a naive 'payee is printed' assertion."""
        from app.cash_disbursements.preprinted_layout import FIELD_KEYS
        assert 'vendor_name' in FIELD_KEYS and 'check_payee' in FIELD_KEYS


class TestItShipsHidden:

    def test_the_default_is_hidden(self):
        """A new field must not appear on a client's pad unasked."""
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        assert sanitize_layout({})['fields']['check_payee']['hidden'] is True

    def test_no_other_field_was_hidden_by_this(self):
        """CONTROL. Shipping the new field hidden must not have flipped its neighbours --
        that would blank fields a client is live on."""
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        fields = sanitize_layout({})['fields']
        assert fields['vendor_name']['hidden'] is False
        assert fields['cdv_no']['hidden'] is False

    def test_a_legacy_layout_still_gets_the_field(self):
        """A blob saved before today names no check_payee at all. It must come back
        present-but-hidden, not missing -- the template subscripts layout.fields[key] for
        every key in FIELD_KEYS, so an absent one is a 500."""
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        out = sanitize_layout({'fields': {'vendor_name': {'x': 100, 'y': 100}}})
        assert out['fields']['check_payee']['hidden'] is True
        assert out['fields']['vendor_name']['x'] == 100      # and the stored one survives


class TestItRenders:

    def test_hidden_by_default_it_carries_the_hidden_marker(self, client, db_session,
                                                            admin_user, main_branch):
        html, _ = _render(client, db_session, main_branch, payee='Johnson Hardware', show=False)
        assert 'pp-field-hidden' in _open_tag(html, 'data-el="check_payee"')

    def test_unhidden_it_prints_the_payee_name(self, client, db_session, admin_user,
                                               main_branch):
        html, _ = _render(client, db_session, main_branch,
                          payee='Juan Dela Cruz', show=True)
        tag = _open_tag(html, 'data-el="check_payee"')
        assert 'pp-field-hidden' not in tag
        assert 'Juan Dela Cruz' in html

    def test_both_names_print_when_they_differ(self, client, db_session, admin_user,
                                               main_branch):
        """THE requirement. The two names differ only rarely, which is exactly why both
        must print: the rare voucher whose cheque names someone else is the one nobody
        can reconcile from memory."""
        html, cdv = _render(client, db_session, main_branch,
                            payee='Juan Dela Cruz', show=True)
        assert cdv.vendor_name != 'Juan Dela Cruz'      # the fixture's names really differ
        assert cdv.vendor_name in html                  # Pay To ...
        assert 'Juan Dela Cruz' in html                 # ... and Check Payee

    def test_a_vendor_with_no_payee_name_renders_empty_not_none(self, client, db_session,
                                                                admin_user, main_branch):
        """The column is nullable and most vendors leave it blank. `None` reaching the
        template would print the literal text "None" onto the stationery."""
        html, _ = _render(client, db_session, main_branch, payee=None, show=True)
        assert 'None' not in _open_tag(html, 'data-el="check_payee"')
        i = html.index('data-el="check_payee"')
        assert '>None<' not in html[i:i + 200]

    def test_it_is_draggable_like_any_other_field(self, client, db_session, admin_user,
                                                  main_branch):
        """data-el is how the designer finds and serialises it; data-label is what the
        Fields strip shows and what an empty field displays so it stays grabbable."""
        html, _ = _render(client, db_session, main_branch, payee='X', show=True)
        assert 'data-el="check_payee"' in html
        assert 'data-label="Check Payee"' in html
