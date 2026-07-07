"""Render a CDV check overlay to PDF (fpdf2).

A check is a negotiable instrument on pre-registered bank stock, so we render a PDF
(exact pt positioning) rather than the siblings' HTML `@page` print (browsers apply
their own scaling). The PDF carries ONLY the variable data — payee/date/figures/words/
memo — at the layout's positions; the physical bank check IS the background. NO
facsimile signature is ever drawn (the wet signature is the binding control).

The same sanitized layout JSON that drives the HTML designer canvas drives this render:
canvas px @96dpi map to PDF pt @72dpi via `pt = px * 0.75`.
"""
from fpdf import FPDF

from app.cash_disbursements.check_layout import PAPER_SIZES

PX_TO_PT = 72.0 / 96.0   # 0.75


def _core_font(font_family):
    """Map the CSS font stack to an fpdf2 built-in core font (no font files needed)."""
    fam = (font_family or '').lower()
    if 'monospace' in fam or 'courier' in fam or 'consolas' in fam or 'lucida console' in fam:
        return 'Courier'
    if 'serif' in fam or 'times' in fam or 'georgia' in fam:
        return 'Times'
    return 'Helvetica'


def _new_pdf(layout):
    paper = PAPER_SIZES[layout['paper']]
    pdf = FPDF(unit='pt', format=(paper['w'] * PX_TO_PT, paper['h'] * PX_TO_PT))
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0, 0)
    pdf.add_page()
    return pdf


def overflowing_field(layout, values, keys):
    """Return the first key in `keys` whose (visible, non-empty) text is wider than its
    field box — the caller refuses to print (a clipped legally-operative line is invalid).
    """
    pdf = _new_pdf(layout)
    core = _core_font(layout['page']['fontFamily'])
    for key in keys:
        f = layout['fields'].get(key)
        text = (values.get(key) or '')
        if not f or f.get('hidden') or not text:
            continue
        pdf.set_font(core, 'B' if f['bold'] else '', f['fontSize'] * PX_TO_PT)
        if pdf.get_string_width(text) > f['width'] * PX_TO_PT:
            return key
    return None


def render_check_pdf(layout, values):
    """Overlay `values` (field_key -> text) onto a blank page at the layout positions.
    Hidden or empty fields are skipped. Returns PDF bytes."""
    pdf = _new_pdf(layout)
    core = _core_font(layout['page']['fontFamily'])
    for key, f in layout['fields'].items():
        if f.get('hidden'):
            continue
        text = (values.get(key) or '')
        if not text:
            continue
        pdf.set_font(core, 'B' if f['bold'] else '', f['fontSize'] * PX_TO_PT)
        pdf.set_xy(f['x'] * PX_TO_PT, f['y'] * PX_TO_PT)
        pdf.cell(f['width'] * PX_TO_PT, f['fontSize'] * PX_TO_PT * 1.2, text)
    return bytes(pdf.output())
