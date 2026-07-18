"""Regression test for R-02 Phase 6: the AP<-PO/RR billing picker must carry the source
line item ids and matched price/quantity into the injected AP line, so the AP form can
snapshot and compare them."""
import pathlib


def test_inject_lines_passes_variance_fields_to_add_line_item():
    js_path = (pathlib.Path(__file__).resolve().parents[2]
              / 'app' / 'static' / 'ap_po_billing.js')
    text = js_path.read_text(encoding='utf-8')
    fn_start = text.index('function injectLines(')
    fn_end = text.index('\n  }\n', fn_start)
    body = text[fn_start:fn_end]
    for expected in ('source_po_item_id: ln.po_item_id',
                     'source_rr_item_id: ln.rr_item_id',
                     'matched_unit_price:', 'matched_quantity:'):
        assert expected in body, f'injectLines() must set {expected!r}'
