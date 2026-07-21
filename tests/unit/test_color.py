"""Unit tests for app.utils.color -- the sidebar-theme HSL derivation
(R-11 #231). See docs/superpowers/specs/2026-07-21-branch-color-themes-design.md
for the formula this pins."""
import colorsys
import pytest

from app.utils.color import is_valid_hex_color, derive_sidebar_theme

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
