"""Sidebar color-theme derivation for per-branch theming (R-11 #231).
Pure functions, stdlib-only. Given one admin-picked hex color, derives every
other sidebar token at render time -- see the Derivation algorithm table in
docs/superpowers/specs/2026-07-21-branch-color-themes-design.md.
"""
import colorsys
import re

HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def is_valid_hex_color(value):
    """True if value is a well-formed '#RRGGBB' string."""
    return bool(value) and bool(HEX_COLOR_RE.match(value))


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r, g, b):
    clamp = lambda v: max(0, min(255, round(v)))
    return '#{:02x}{:02x}{:02x}'.format(clamp(r), clamp(g), clamp(b))


def _hls_to_hex(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return _rgb_to_hex(r * 255, g * 255, b * 255)


def derive_sidebar_theme(hex_color):
    """Derive the 5 sidebar CSS tokens from one admin-picked hex color.

    Raises ValueError if hex_color is not a well-formed '#RRGGBB' string.
    """
    if not is_valid_hex_color(hex_color):
        raise ValueError(f'Invalid hex color: {hex_color!r}')

    r, g, b = _hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)

    bg_s = min(s, 0.50)
    bg_l = max(0.10, min(0.16, l))
    bg = _hls_to_hex(h, bg_l, bg_s)

    hover_l = min(bg_l + 0.06, 1.0)
    hover = _hls_to_hex(h, hover_l, bg_s)

    active_text = _hls_to_hex(h, 0.80, 0.60)

    return {
        'bg': bg,
        'hover': hover,
        'active_bg': f'rgba({r}, {g}, {b}, 0.15)',
        'active_text': active_text,
        'active_border': hex_color,
    }
