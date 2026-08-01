"""Unit tests for app.utils.color -- the sidebar-theme HSL derivation
(R-11 #231). See docs/superpowers/specs/2026-07-21-branch-color-themes-design.md
for the formula this pins."""
import colorsys
import pytest

from app.utils.color import is_valid_hex_color, derive_sidebar_theme, derive_chip_theme

pytestmark = [pytest.mark.unit]


def _hex_to_lightness(hex_color):
    hex_color = hex_color.lstrip('#')
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    _, l, _ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return l


class TestIsValidHexColor:
    def test_accepts_well_formed_hex(self):
        assert is_valid_hex_color('#3b82f6') is True
        assert is_valid_hex_color('#FFFFFF') is True

    @pytest.mark.parametrize('bad', [
        'blue', '#zzzzzz', '#fff', '3b82f6', '#3b82f', '', None,
    ])
    def test_rejects_malformed_input(self, bad):
        assert is_valid_hex_color(bad) is False


class TestDeriveSidebarTheme:
    @pytest.mark.parametrize('hex_color', [
        '#3b82f6',  # saturated primary (the app's own --blue)
        '#fbcfe8',  # pastel
        '#050505',  # near-black
        '#fefefe',  # near-white
        '#808080',  # pure gray / zero saturation
    ])
    def test_bg_lightness_always_clamped(self, hex_color):
        derived = derive_sidebar_theme(hex_color)
        # Tolerance covers 8-bit hex round-trip quantization (derive ->
        # rgb -> hex -> back to rgb -> hls loses ~1/255 per channel), not
        # slack in the clamp itself -- max observed drift is ~0.0008.
        tolerance = 0.002
        assert 0.10 - tolerance <= _hex_to_lightness(derived['bg']) <= 0.16 + tolerance

    @pytest.mark.parametrize('hex_color', [
        '#3b82f6', '#fbcfe8', '#050505', '#fefefe', '#808080',
    ])
    def test_all_values_are_well_formed(self, hex_color):
        derived = derive_sidebar_theme(hex_color)
        assert is_valid_hex_color(derived['bg'])
        assert is_valid_hex_color(derived['hover'])
        assert is_valid_hex_color(derived['active_text'])
        assert is_valid_hex_color(derived['active_border'])
        assert derived['active_bg'].startswith('rgba(') and derived['active_bg'].endswith(')')

    def test_hover_is_lighter_than_bg(self):
        derived = derive_sidebar_theme('#3b82f6')
        assert _hex_to_lightness(derived['hover']) > _hex_to_lightness(derived['bg'])

    def test_active_border_passes_through_unmodified(self):
        derived = derive_sidebar_theme('#3b82f6')
        assert derived['active_border'] == '#3b82f6'

    def test_active_bg_matches_todays_blue_token_exactly_for_blue_input(self):
        # Sanity check: picking the app's own --blue should reproduce today's
        # hardcoded --sidebar-active-bg: rgba(59,130,246,.15) exactly.
        derived = derive_sidebar_theme('#3b82f6')
        assert derived['active_bg'] == 'rgba(59, 130, 246, 0.15)'

    def test_raises_on_malformed_hex(self):
        with pytest.raises(ValueError):
            derive_sidebar_theme('not-a-color')


class TestDeriveChipTheme:
    """Light-background chip variant (combined AR aging report branch chips,
    2026-08-01). Same hue-preserving HLS approach as derive_sidebar_theme, but
    the lightness clamps are inverted for a LIGHT chip (pale tint bg, dark
    ink) instead of the dark sidebar -- and both bg and fg lightness are
    clamped into a fixed band regardless of the *input* color's own
    lightness, so a near-white or near-black stored theme_color still
    produces a legible chip."""

    @pytest.mark.parametrize('hex_color', [
        '#3b82f6',  # saturated primary
        '#fbcfe8',  # pastel
        '#050505',  # near-black
        '#fefefe',  # near-white
        '#808080',  # pure gray / zero saturation
    ])
    def test_all_values_are_well_formed(self, hex_color):
        derived = derive_chip_theme(hex_color)
        assert is_valid_hex_color(derived['bg'])
        assert is_valid_hex_color(derived['fg'])
        assert is_valid_hex_color(derived['border'])

    @pytest.mark.parametrize('hex_color', [
        '#3b82f6', '#fbcfe8', '#050505', '#fefefe', '#808080', '#ffffff', '#000000',
    ])
    def test_fg_lightness_always_clamped_for_legibility(self, hex_color):
        """The text/ink color must land in a fixed dark-enough band no matter
        how light or dark the stored color is -- this is what keeps a
        near-white or near-black branch theme_color readable against the
        pale chip background."""
        derived = derive_chip_theme(hex_color)
        tolerance = 0.01
        assert 0.28 - tolerance <= _hex_to_lightness(derived['fg']) <= 0.42 + tolerance

    @pytest.mark.parametrize('hex_color', [
        '#3b82f6', '#fbcfe8', '#050505', '#fefefe', '#808080', '#ffffff', '#000000',
    ])
    def test_bg_is_a_pale_tint_regardless_of_input_lightness(self, hex_color):
        derived = derive_chip_theme(hex_color)
        assert _hex_to_lightness(derived['bg']) >= 0.88

    def test_fg_is_darker_than_bg(self):
        derived = derive_chip_theme('#3b82f6')
        assert _hex_to_lightness(derived['fg']) < _hex_to_lightness(derived['bg'])

    def test_raises_on_malformed_hex(self):
        with pytest.raises(ValueError):
            derive_chip_theme('not-a-color')
