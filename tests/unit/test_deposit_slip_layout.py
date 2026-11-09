"""Deposit slip layouts: one per bank form (owner, 10 Nov 2026: "CAS-Q2, yes"), sanitized like the
cheque layout. Design: app-docs/superpowers/specs/2026-11-10-deposit-slip-print-design.md."""
import pytest

from app.common import deposit_slip as ds

pytestmark = [pytest.mark.unit, pytest.mark.cash_disbursements]


def test_two_forms_chinabank_first():
    assert list(ds.FORMS) == ['chinabank_bnk108', 'bdo_v062019']
    assert ds.FORMS['chinabank_bnk108']['label'] == 'Chinabank Check Deposit Slip (BNK-108)'
    assert ds.FORMS['bdo_v062019']['label'] == 'BDO Check Transaction Slip (V062019)'


def test_every_form_lays_out_the_same_fields():
    assert ds.FIELD_KEYS == ['deposit_date', 'account_name', 'account_number', 'total_amount',
                             'check_bank', 'check_number', 'check_amount']
    for key in ds.FORMS:
        assert list(ds.default_layout(key)['fields']) == ds.FIELD_KEYS


def test_defaults_are_letter_arial_narrow_bold_and_no_nudge():
    layout = ds.default_layout('chinabank_bnk108')
    assert layout['paper'] == 'letter'
    assert layout['page'] == {'fontFamily': '"Arial Narrow", Arial, sans-serif',
                              'offsetX': 0.0, 'offsetY': 0.0}
    assert all(f['bold'] and f['fontSize'] == 13 for f in layout['fields'].values())
    assert layout['texts'] == []   # no X marks (owner, 9 Nov: "remove the X marks")


def test_chinabank_starts_where_the_interim_slip_printed():
    """mm from the slip's top-left: the interim baselines less 0.86 em and the 1.2 mm found on the
    9 Nov test print, at 96 px per inch."""
    f = ds.default_layout('chinabank_bnk108')['fields']
    assert (f['deposit_date']['x'], f['deposit_date']['y']) == (42, 61)
    assert (f['account_name']['x'], f['account_name']['y']) == (272, 158)
    assert (f['account_number']['x'], f['account_number']['y']) == (42, 182)
    assert (f['total_amount']['x'], f['total_amount']['y']) == (42, 226)
    assert (f['check_bank']['x'], f['check_bank']['y']) == (49, 300)
    assert (f['check_number']['x'], f['check_number']['y']) == (261, 300)
    # the cheque amount ends at the column's right border, 139 mm
    amt = f['check_amount']
    assert amt['align'] == 'right' and amt['x'] + amt['width'] == 525 and amt['y'] == 300


def test_bdo_starts_where_the_interim_slip_printed():
    f = ds.default_layout('bdo_v062019')['fields']
    assert (f['deposit_date']['x'], f['deposit_date']['y']) == (726, 39)
    assert (f['account_name']['x'], f['account_name']['y']) == (136, 67)
    assert (f['account_number']['x'], f['account_number']['y']) == (136, 97)
    assert (f['check_bank']['x'], f['check_number']['x'], f['check_amount']['x']) == (501, 610, 707)
    assert f['check_amount']['align'] == 'left'   # the LQ-310 prints 8in wide
    assert (f['total_amount']['x'], f['total_amount']['y']) == (707, 332)


def test_an_unknown_form_is_refused():
    with pytest.raises(KeyError):
        ds.default_layout('bpi_unknown')


def test_sanitize_keeps_a_good_layout_and_clamps_a_bad_one():
    raw = ds.default_layout('chinabank_bnk108')
    raw['fields']['account_name'].update(x=9999, y=-5, fontSize=200, width=3)
    raw['page'].update(fontFamily='Comic Sans', offsetX=99, offsetY='-1.24')
    clean = ds.sanitize_layout('chinabank_bnk108', raw)
    name = clean['fields']['account_name']
    assert (name['x'], name['y'], name['fontSize'], name['width']) == (816, 0, 72, 10)
    assert clean['page'] == {'fontFamily': '"Arial Narrow", Arial, sans-serif',
                             'offsetX': 20.0, 'offsetY': -1.2}


def test_sanitize_fills_what_the_designer_does_not_send():
    """The cheque designer posts no `align`; a saved field keeps its form's default."""
    raw = {'fields': {'check_amount': {'x': 300, 'y': 290, 'fontSize': 13, 'bold': True, 'width': 120}}}
    clean = ds.sanitize_layout('chinabank_bnk108', raw)
    assert clean['fields']['check_amount']['align'] == 'right'
    assert clean['fields']['account_name'] == ds.default_layout('chinabank_bnk108')['fields']['account_name']
    assert clean['paper'] == 'letter'


@pytest.mark.parametrize('bank, form', [
    ('BDO', 'bdo_v062019'),
    ('BDO Unibank', 'bdo_v062019'),
    ('bdo masangkay', 'bdo_v062019'),
    ('CHINA BANK', 'chinabank_bnk108'),
    ('CBC', 'chinabank_bnk108'),
    ('BPI', 'chinabank_bnk108'),
    ('', 'chinabank_bnk108'),
    (None, 'chinabank_bnk108'),
])
def test_the_form_defaults_from_the_deposit_account_bank(bank, form):
    assert ds.default_form_for(bank) == form


def test_the_slip_fonts_offer_arial_narrow_first():
    assert ds.ALLOWED_FONTS[0] == '"Arial Narrow", Arial, sans-serif'
    assert '"Courier New", Courier, monospace' in ds.ALLOWED_FONTS
