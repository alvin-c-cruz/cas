import pytest
from app import db
from app.preprinted_forms.models import PrintLayout, VOUCHER_TYPES

pytestmark = [pytest.mark.unit]

def test_json_round_trip(db_session):
    pl = PrintLayout(voucher_type='JV', active=True, page_width_mm=215.9, page_height_mm=279.4)
    pl.set_fields([{'key': 'date', 'x_mm': 20, 'y_mm': 30, 'font_size': 10, 'align': 'L', 'visible': True}])
    pl.set_line_band({'anchor_y_mm': 80, 'row_height_mm': 6, 'max_rows': 12, 'font_size': 9,
                      'columns': [{'key': 'account_code', 'x_mm': 15, 'width_mm': 30, 'align': 'L'}]})
    db.session.add(pl); db.session.commit()
    got = db.session.get(PrintLayout, pl.id)
    assert got.get_fields()[0]['key'] == 'date'
    assert got.get_line_band()['max_rows'] == 12
    assert VOUCHER_TYPES == ('SI', 'CR', 'CD', 'AP', 'JV', 'CD_CHECK')

def test_bad_json_is_safe(db_session):
    pl = PrintLayout(voucher_type='SI'); pl.fields_json = 'not json'; pl.line_band_json = '{bad'
    assert pl.get_fields() == [] and pl.get_line_band() == {}

def test_printlayout_account_id_and_composite_unique(db_session):
    db.session.add_all([PrintLayout(voucher_type='CD_CHECK', account_id=None),
                        PrintLayout(voucher_type='CD_CHECK', account_id=1)])
    db.session.commit()
    assert PrintLayout.query.filter_by(voucher_type='CD_CHECK').count() == 2
