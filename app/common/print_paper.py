"""Custom paper size and whole-page shift for every pre-printed layout and the cheque (RICL-1 A, RICL-2 A).

Owner, 17 Nov 2026, for RIC's forms (6.5-in continuous, a ~7 x 8.5 pad, a ~8.5 x 9.3 pad): RICL-1 A, a "Custom size"
paper (width x height in inches) beside the two fixed papers on every pre-printed layout and the cheque; RICL-2 A, a
"Shift whole page" x/y in mm on each layout, so one test print, measured, moves every field at once. The deposit
slip's "Nudge print (mm)" (`app.common.deposit_slip`) is the model: the shift applies on paper only.

Both are plain keys inside the layout JSON (`paper: 'custom'`, `paperSize: {w, h}` in inches, `offset: {x, y}` in mm),
so there is no migration. Every module's sanitizer calls `clean_paper`, and a layout saved before this existed reads
back with no shift and the default custom size (remembered even while a fixed paper is chosen).

The widest custom paper is the designer canvas itself (9.5 in, 912 px): every sanitizer clamps x against that canvas.
The tallest is 11 in, like Letter; as on Letter, y still clamps at the 10.5-in canvas, so a field cannot sit in the
last half inch.
"""
import math

CUSTOM = 'custom'
CUSTOM_LABEL = 'Custom size'
PX_PER_IN = 96
W_MIN_IN, W_MAX_IN = 2.0, 9.5
H_MIN_IN, H_MAX_IN = 2.0, 11.0
DEFAULT_PAPER_SIZE = {'w': 9.5, 'h': 5.5}
OFFSET_MAX_MM = 20.0


def _num(value, lo, hi, fallback, ndigits):
    """A finite number rounded to `ndigits`, clamped to lo..hi; anything else is `fallback`.

    bool is refused (True would read as 1), and so are NaN and the infinities JSON can carry (`1e999`)."""
    if isinstance(value, bool):
        return fallback
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if not math.isfinite(n):
        return fallback
    return round(max(lo, min(hi, n)), ndigits)


def clean_paper_size(raw):
    """{'w', 'h'} in inches, two decimals, each side clamped on its own."""
    raw = raw if isinstance(raw, dict) else {}
    return {'w': _num(raw.get('w'), W_MIN_IN, W_MAX_IN, DEFAULT_PAPER_SIZE['w'], 2),
            'h': _num(raw.get('h'), H_MIN_IN, H_MAX_IN, DEFAULT_PAPER_SIZE['h'], 2)}


def clean_offset(raw):
    """{'x', 'y'} in mm, one decimal, within +/- OFFSET_MAX_MM; + moves right / down."""
    raw = raw if isinstance(raw, dict) else {}
    return {'x': _num(raw.get('x'), -OFFSET_MAX_MM, OFFSET_MAX_MM, 0.0, 1),
            'y': _num(raw.get('y'), -OFFSET_MAX_MM, OFFSET_MAX_MM, 0.0, 1)}


def clean_paper(raw, allowed_papers, default_paper):
    """The layout's paper keys: `paper` (a fixed paper, or 'custom'), `paperSize` and `offset`.

    Membership is tested with `==` against a tuple, so an unhashable stored value cannot raise."""
    raw = raw if isinstance(raw, dict) else {}
    paper = raw.get('paper')
    if not isinstance(paper, str) or (paper not in allowed_papers and paper != CUSTOM):
        paper = default_paper
    return {'paper': paper,
            'paperSize': clean_paper_size(raw.get('paperSize')),
            'offset': clean_offset(raw.get('offset'))}


def css_inches(value):
    """9.5 -> '9.5in', 7.0 -> '7in' (the @page rule and the paper <option> carry this)."""
    return f'{float(value):g}in'


def paper_ctx(layout, paper_sizes, paper_labels):
    """`paper_sizes` / `paper_labels` for a print template, with this layout's custom size added.

    The templates already read `paper_sizes[layout.paper]` for the canvas and the @page rule, and loop over
    `paper_sizes` for the paper <select>; adding 'custom' here makes both work for a custom paper unchanged.
    New dicts every call: the module constants are shared by every request."""
    size = clean_paper_size((layout or {}).get('paperSize'))
    sizes = dict(paper_sizes)
    sizes[CUSTOM] = {'w': round(size['w'] * PX_PER_IN), 'h': round(size['h'] * PX_PER_IN),
                     'css': f"{css_inches(size['w'])} {css_inches(size['h'])}"}
    labels = dict(paper_labels)
    labels[CUSTOM] = CUSTOM_LABEL
    return {'paper_sizes': sizes, 'paper_labels': labels}
