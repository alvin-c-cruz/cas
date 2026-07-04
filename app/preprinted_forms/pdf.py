"""PDF overlay generator for pre-printed voucher forms (P-69).

Renders a data-only overlay for a voucher record positioned per a
``PrintLayout`` (header fields + a line band), meant to be printed on
physical pre-printed paper forms. Only the core ``Helvetica`` font is used
(no TTF is registered), so every string rendered must be latin-1-safe; see
``_text`` below.
"""
from fpdf import FPDF

from app.preprinted_forms.field_catalog import resolve_field, resolve_line_value, iter_lines

_DEFAULT_FIELD_WIDTH_MM = 40


def can_print(voucher_type, record):
    """Server-side mirror of each document detail-template's Print-button
    condition (P-69 Task 7) -- the print ROUTES had no access/status gate
    before this; the *_print_access settings were previously read only to
    decide whether to render the Print button, never enforced server-side.
    Returns bool."""
    from app.settings import AppSettings
    if voucher_type == 'SI':
        setting = AppSettings.get_setting('sv_print_access', 'posted_only')
        posted_ok = record.status in ('posted', 'partially_paid', 'paid')
    elif voucher_type == 'AP':
        setting = AppSettings.get_setting('apv_print_access', 'posted_only')
        posted_ok = record.status in ('posted', 'partially_paid', 'paid')
    elif voucher_type == 'CR':
        setting = AppSettings.get_setting('cr_print_access', 'posted_only')
        posted_ok = record.status == 'posted'
    elif voucher_type == 'CD':
        setting = AppSettings.get_setting('cd_print_access', 'posted_only')
        posted_ok = record.status == 'posted'
    elif voucher_type == 'CD_CHECK':
        setting = AppSettings.get_setting('cd_check_print_access', 'posted_only')
        posted_ok = record.status == 'posted'
    elif voucher_type == 'JV':
        return True  # no *_print_access setting exists for JV today -- default allow (decided)
    else:
        return False
    if setting == 'posted_only':
        return posted_ok
    if setting == 'draft_and_posted':
        return record.status not in ('voided', 'cancelled')
    return posted_ok


def preprinted_response(voucher_type, record):
    """Return a PDF Response if pre-printed mode is on for this voucher, else None.

    None means "fall through to the existing HTML print template" -- callers
    must not treat None as an error."""
    from flask import Response
    from app.users.module_access import module_enabled
    from app.preprinted_forms.models import PrintLayout
    if not module_enabled('preprinted_forms'):
        return None
    layout = PrintLayout.query.filter_by(voucher_type=voucher_type, active=True).first()
    if not layout or not layout.background_image:
        return None
    pdf_bytes = render_preprinted(layout, record)
    return Response(pdf_bytes, mimetype='application/pdf',
                     headers={'Content-Disposition': f'inline; filename="{voucher_type.lower()}.pdf"'})


def _sanitize(s):
    """Strip any character that can't be represented in latin-1 (core PDF
    fonts are latin-1 only). A stray '₱' (peso sign) is dropped, not
    replaced -- per the P-69 decision, no currency sign is ever printed."""
    return s.encode('latin-1', 'ignore').decode('latin-1')


def _text(pdf, f, s):
    s = _sanitize(str(s))
    # Empty strings are no-ops; skip to avoid fpdf2 ValueError on empty fragments.
    if not s:
        return
    pdf.set_font('Helvetica', size=f.get('font_size', 10))
    x = float(f['x_mm'])
    y = float(f['y_mm'])
    align = f.get('align', 'L')
    if align in ('R', 'C'):
        width = float(f.get('width_mm') or _DEFAULT_FIELD_WIDTH_MM)
        pdf.set_xy(x, y)
        pdf.cell(w=width, align=align, text=s)
    else:
        width = float(f.get('width_mm') or _DEFAULT_FIELD_WIDTH_MM)
        pdf.set_xy(x, y)
        pdf.cell(w=width, align='L', text=s)


def _draw_background(pdf, layout, w, h):
    """Draw the layout's background image full-page, as an alignment aid
    for test/preview renders. Skipped gracefully if the file is missing or
    there is no Flask app context (never raises)."""
    try:
        from flask import current_app
        import os
        upload_folder = current_app.config['UPLOAD_FOLDER']
        path = os.path.join(upload_folder, 'preprinted', layout.background_image)
        if not os.path.isfile(path):
            return
        pdf.image(path, 0, 0, w, h)
    except Exception:
        return


def render_preprinted(layout, record, *, test=False):
    """Render a voucher record as a data-only PDF overlay per ``layout``.

    Returns the PDF file bytes. When ``test=True`` and the layout has a
    ``background_image``, the image is drawn full-page first as an
    alignment aid (never drawn in normal, data-only mode).
    """
    w = float(layout.page_width_mm)
    h = float(layout.page_height_mm)
    pdf = FPDF(orientation='P', unit='mm', format=(w, h))
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0, 0)
    pdf.add_page()

    if test and layout.background_image:
        _draw_background(pdf, layout, w, h)

    vt = layout.voucher_type

    for f in layout.get_fields():
        if not f.get('visible', True):
            continue
        val = resolve_field(vt, f['key'], record)
        _text(pdf, f, str(val))

    band = layout.get_line_band()
    if band and band.get('columns'):
        # max_rows: 0 is treated as unlimited (0 → falsy → None for slice).
        max_rows = int(band.get('max_rows', 0)) or None
        rows = iter_lines(vt, record)[:max_rows]
        for i, line in enumerate(rows):
            y = float(band['anchor_y_mm']) + i * float(band['row_height_mm'])
            for col in band['columns']:
                val = resolve_line_value(vt, col['key'], line)
                _text(pdf, {
                    'x_mm': col['x_mm'],
                    'y_mm': y,
                    'align': col.get('align', 'L'),
                    'font_size': band.get('font_size', 9),
                    'width_mm': col.get('width_mm'),
                }, str(val))

    return bytes(pdf.output())
