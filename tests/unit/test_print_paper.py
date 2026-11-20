"""RICL-1 A + RICL-2 A: a "Custom size" paper and a "Shift whole page" on every pre-printed layout and the cheque.

Owner, 17 Nov 2026 (RICL-1 A): "Custom size" (width x height in inches) beside the two fixed papers, on every
pre-printed layout and the cheque. RICL-2 A: a whole-page x/y shift in mm per layout, applied on paper only, so one
test print aligns every field. Both live inside the layout JSON (no migration), sanitized like every other key.
"""
import importlib
import math

import pytest

from app.common import print_paper as pp

pytestmark = [pytest.mark.unit]


class TestCleanPaperSize:

    def test_missing_gives_the_default(self):
        assert pp.clean_paper_size(None) == pp.DEFAULT_PAPER_SIZE
        assert pp.clean_paper_size({}) == pp.DEFAULT_PAPER_SIZE
        assert pp.clean_paper_size('9.5x6.5') == pp.DEFAULT_PAPER_SIZE

    def test_keeps_two_decimals(self):
        assert pp.clean_paper_size({'w': '9.5', 'h': 6.504}) == {'w': 9.5, 'h': 6.5}
        assert pp.clean_paper_size({'w': 8.5, 'h': 9.33}) == {'w': 8.5, 'h': 9.33}

    def test_clamps_to_the_printable_range(self):
        out = pp.clean_paper_size({'w': 30, 'h': 0.5})
        assert out == {'w': pp.W_MAX_IN, 'h': pp.H_MIN_IN}
        out = pp.clean_paper_size({'w': -1, 'h': 99})
        assert out == {'w': pp.W_MIN_IN, 'h': pp.H_MAX_IN}

    @pytest.mark.parametrize('junk', [None, 'wide', [1], {'a': 1}, float('nan'), float('inf'), 1e999, True])
    def test_junk_falls_back_per_side(self, junk):
        out = pp.clean_paper_size({'w': junk, 'h': 7})
        assert out == {'w': pp.DEFAULT_PAPER_SIZE['w'], 'h': 7.0}

    def test_widest_custom_fits_the_designer_canvas(self):
        # x is clamped against the 9.5in (912px) canvas in every sanitizer
        assert pp.W_MAX_IN * pp.PX_PER_IN <= 912


class TestCleanOffset:

    def test_missing_is_zero(self):
        assert pp.clean_offset(None) == {'x': 0.0, 'y': 0.0}
        assert pp.clean_offset([]) == {'x': 0.0, 'y': 0.0}

    def test_one_decimal_mm_and_sign_kept(self):
        assert pp.clean_offset({'x': '1.26', 'y': -2.04}) == {'x': 1.3, 'y': -2.0}

    def test_clamped_to_the_limit(self):
        assert pp.clean_offset({'x': 50, 'y': -50}) == {'x': pp.OFFSET_MAX_MM, 'y': -pp.OFFSET_MAX_MM}

    @pytest.mark.parametrize('junk', ['up', None, [2], float('nan'), float('-inf'), True])
    def test_junk_is_zero(self, junk):
        assert pp.clean_offset({'x': junk, 'y': 3}) == {'x': 0.0, 'y': 3.0}


class TestCleanPaper:

    ALLOWED = ('continuous', 'letter')

    def test_custom_is_accepted_beside_the_fixed_papers(self):
        out = pp.clean_paper({'paper': 'custom', 'paperSize': {'w': 9.5, 'h': 6.5}}, self.ALLOWED, 'continuous')
        assert out == {'paper': 'custom', 'paperSize': {'w': 9.5, 'h': 6.5}, 'offset': {'x': 0.0, 'y': 0.0}}

    def test_fixed_paper_kept_and_size_still_remembered(self):
        out = pp.clean_paper({'paper': 'letter', 'paperSize': {'w': 7, 'h': 8.5}, 'offset': {'x': 1, 'y': 2}},
                             self.ALLOWED, 'continuous')
        assert out == {'paper': 'letter', 'paperSize': {'w': 7.0, 'h': 8.5}, 'offset': {'x': 1.0, 'y': 2.0}}

    @pytest.mark.parametrize('bad', ['a4', None, ['custom'], {'p': 1}])
    def test_unknown_paper_falls_back_to_the_default(self, bad):
        assert pp.clean_paper({'paper': bad}, self.ALLOWED, 'letter')['paper'] == 'letter'

    def test_non_dict_raw(self):
        assert pp.clean_paper('junk', self.ALLOWED, 'continuous') == {
            'paper': 'continuous', 'paperSize': pp.DEFAULT_PAPER_SIZE, 'offset': {'x': 0.0, 'y': 0.0}}


class TestPaperContext:

    SIZES = {'continuous': {'w': 912, 'h': 1008, 'css': '9.5in 10.5in'},
             'letter': {'w': 816, 'h': 1056, 'css': '8.5in 11in'}}
    LABELS = {'continuous': '9.5 x 10.5 continuous paper', 'letter': 'Letter 8.5 x 11'}

    def test_adds_this_layouts_custom_size(self):
        ctx = pp.paper_ctx({'paper': 'custom', 'paperSize': {'w': 9.5, 'h': 6.5}}, self.SIZES, self.LABELS)
        assert ctx['paper_sizes']['custom'] == {'w': 912, 'h': 624, 'css': '9.5in 6.5in'}
        assert ctx['paper_labels']['custom'] == 'Custom size'
        assert list(ctx['paper_sizes']) == ['continuous', 'letter', 'custom']

    def test_does_not_mutate_the_module_constants(self):
        pp.paper_ctx({'paper': 'custom', 'paperSize': {'w': 7, 'h': 8.5}}, self.SIZES, self.LABELS)
        assert 'custom' not in self.SIZES and 'custom' not in self.LABELS

    def test_a_layout_without_a_size_gets_the_default(self):
        ctx = pp.paper_ctx({'paper': 'continuous'}, self.SIZES, self.LABELS)
        d = pp.DEFAULT_PAPER_SIZE
        assert ctx['paper_sizes']['custom']['w'] == round(d['w'] * 96)
        assert ctx['paper_sizes']['continuous'] == self.SIZES['continuous']

    def test_css_has_no_trailing_zeros(self):
        assert pp.css_inches(8.5) == '8.5in' and pp.css_inches(7.0) == '7in' and pp.css_inches(9.33) == '9.33in'


# Every pre-printed layout and the cheque: (module path, sanitize callable name).
LAYOUT_MODULES = [
    'app.sales_orders.preprinted_layout',
    'app.sales_invoices.preprinted_layout',
    'app.accounts_payable.preprinted_layout',
    'app.cash_disbursements.preprinted_layout',
    'app.cash_receipts.preprinted_layout',
    'app.journal_entries.preprinted_layout',
    'app.delivery_receipts.preprinted_layout',
    'app.payroll.preprinted_layout',
    'app.purchase_orders.preprinted_layout',
    'app.purchase_requests.preprinted_layout',
    'app.receiving_reports.preprinted_layout',
    'app.cash_disbursements.check_layout',
]


@pytest.mark.parametrize('modpath', LAYOUT_MODULES, ids=lambda m: m.split('.')[1] + '.' + m.split('.')[2])
class TestEveryLayout:

    def test_custom_size_and_shift_survive_sanitizing(self, modpath):
        mod = importlib.import_module(modpath)
        out = mod.sanitize_layout({'paper': 'custom', 'paperSize': {'w': 9.5, 'h': 6.5},
                                   'offset': {'x': 1.2, 'y': -0.8}})
        assert out['paper'] == 'custom'
        assert out['paperSize'] == {'w': 9.5, 'h': 6.5}
        assert out['offset'] == {'x': 1.2, 'y': -0.8}

    def test_an_old_stored_layout_gets_no_shift(self, modpath):
        mod = importlib.import_module(modpath)
        out = mod.sanitize_layout({'paper': 'letter'})
        assert out['paper'] == 'letter'
        assert out['offset'] == {'x': 0.0, 'y': 0.0}
        assert out['paperSize'] == pp.DEFAULT_PAPER_SIZE

    def test_paper_ctx_resolves_the_custom_canvas(self, modpath):
        mod = importlib.import_module(modpath)
        out = mod.sanitize_layout({'paper': 'custom', 'paperSize': {'w': 7, 'h': 8.5}})
        from app.common import preprinted_base as base   # PO / PR / RR take their papers from the base
        ctx = pp.paper_ctx(out, getattr(mod, 'PAPER_SIZES', base.PAPER_SIZES),
                           getattr(mod, 'PAPER_LABELS', base.PAPER_LABELS))
        assert ctx['paper_sizes'][out['paper']] == {'w': 672, 'h': 816, 'css': '7in 8.5in'}
        assert not math.isnan(out['offset']['x'])
