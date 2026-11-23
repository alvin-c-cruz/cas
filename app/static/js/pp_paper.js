/* Custom paper size (RICL-1 A) and whole-page shift (RICL-2 A) for every pre-printed designer and the cheque.
 *
 * The page renders these controls from templates/_pp_paper_extra.html, right after the paper picker. Each designer
 * already resizes the canvas and rewrites the @page rule from the selected <option>'s data-w / data-h / data-css when
 * the picker changes; this script keeps the "Custom size" option's data in step with the W x H boxes and re-fires
 * that change, so no designer needs its own custom-size code. The shift rewrites the print rule live: the same rule
 * templates/_pp_print_shift.html renders (the canvas clips at the paper's edge; the fields move inside it, SHIFT-SCALE).
 * Each designer's collect() spreads window.ppPaperExtra() beside `paper`, so the save carries both; the server
 * clamps them again (app/common/print_paper.py).
 */
(function () {
  'use strict';
  const sel = document.getElementById('ppPaper');
  const wrap = document.getElementById('ppPaperExtra');
  if (!sel || !wrap) return;
  const PX_PER_IN = 96;
  const wIn = document.getElementById('ppPaperW');
  const hIn = document.getElementById('ppPaperH');
  const sizeBox = document.getElementById('ppCustomSize');
  const sx = document.getElementById('ppShiftX');
  const sy = document.getElementById('ppShiftY');
  const shiftStyle = document.getElementById('ppShiftStyle');
  const customOpt = sel.querySelector('option[value="custom"]');

  // A number inside the input's own min/max, rounded; an empty or junk box gives `dflt`.
  function val(input, digits, dflt) {
    let v = parseFloat(input.value);
    if (!isFinite(v)) v = dflt;
    const lo = parseFloat(input.min), hi = parseFloat(input.max);
    if (isFinite(lo)) v = Math.max(lo, v);
    if (isFinite(hi)) v = Math.min(hi, v);
    const f = Math.pow(10, digits);
    return Math.round(v * f) / f;
  }

  function size() {
    return { w: val(wIn, 2, parseFloat(wIn.defaultValue) || 9.5), h: val(hIn, 2, parseFloat(hIn.defaultValue) || 5.5) };
  }

  function shift() {
    return { x: val(sx, 1, 0), y: val(sy, 1, 0) };
  }

  function syncCustomOption(refire) {
    if (!customOpt) return;
    const s = size();
    customOpt.dataset.w = String(Math.round(s.w * PX_PER_IN));
    customOpt.dataset.h = String(Math.round(s.h * PX_PER_IN));
    customOpt.dataset.css = s.w + 'in ' + s.h + 'in';
    if (refire && sel.value === 'custom') sel.dispatchEvent(new Event('change'));
  }

  function syncVisibility() {
    // The designers show the paper picker only in edit mode; these controls follow it.
    wrap.style.display = sel.style.display === 'none' ? 'none' : '';
    sizeBox.style.display = sel.value === 'custom' ? '' : 'none';
  }

  function syncShift() {
    const s = shift();
    if (!shiftStyle) return;
    shiftStyle.textContent = '@media print { #ppCanvas { overflow: hidden; } #ppCanvas .pp-el, #ppCanvas .pp-col, #ppCanvas .pp-jecol { translate: ' + s.x + 'mm ' + s.y + 'mm; } }';
  }

  [wIn, hIn].forEach((input) => input.addEventListener('input', () => syncCustomOption(true)));
  [sx, sy].forEach((input) => input.addEventListener('input', syncShift));
  sel.addEventListener('change', syncVisibility);
  new MutationObserver(syncVisibility).observe(sel, { attributes: true, attributeFilter: ['style'] });
  syncCustomOption(false);
  syncVisibility();

  window.ppPaperExtra = function () {
    return { paperSize: size(), offset: shift() };
  };

  /* Fields off the page (RICL-W A, owner 23 Nov 2026). A field past the paper's edge -- left there by a smaller
   * paper, saved on a bigger one, or dragged down a short paper (the designers clamp y to 1008 px whatever the paper)
   * -- is listed in a bar and outlined in red, on screen only, from the moment the page opens. Nothing is moved for
   * the user. Hidden fields, switched-off bands and the inactive journal-entry faces do not print, so they do not
   * count. A band (a line-item or JE column, a JE table) counts by its first row: more rows than the paper holds is
   * the document's length, not the layout. The check re-runs on any change to the canvas (paper, drag, font, text),
   * so it works the same under all eight designers without any of them calling it. */
  const HIDDEN = '.pp-field-hidden, .pp-col-hidden, .pp-band-off, .pp-je-inactive';
  const TARGETS = '.pp-el, .pp-col, .pp-jecol';
  const BANDS = '.pp-col, .pp-jecol, [data-je]';
  const JE_LABELS = { combined: 'Journal entry', debit: 'Journal entry debits', credit: 'Journal entry credits',
                      untied: 'Journal entry' };
  const SLACK = 1;   // px of rounding

  function labelOf(el) {
    const raw = el.classList.contains('pp-text') ? el.textContent        // the text as typed now
      : (el.dataset.label || JE_LABELS[el.dataset.je] || el.dataset.el || el.dataset.col || el.dataset.jecol || '');
    let label = raw.replace(/\s+/g, ' ').trim().replace(/:$/, '');
    if (label.length > 40) label = label.slice(0, 39) + '…';
    return el.matches('.pp-col, .pp-jecol') ? label + ' column' : label;
  }

  function isOff(el, page) {
    if (el.closest(HIDDEN)) return false;
    if (el.parentElement && el.parentElement.closest(TARGETS)) return false;   // part of a field, counted with it
    if (!el.getClientRects().length) return false;                              // not rendered
    const r = el.getBoundingClientRect();
    const right = Math.max(r.right, r.left + el.scrollWidth);
    let bottom = r.bottom;
    if (el.matches(BANDS)) {
      const row = el.querySelector('.pp-cell, tr');
      const band = el.closest('[data-rowheight]');
      const rowH = band ? parseFloat(band.dataset.rowheight) || 0 : 0;
      bottom = row ? row.getBoundingClientRect().bottom : r.top + (rowH || r.height);
    } else if (r.height < 1) {
      bottom = r.top + parseFloat(getComputedStyle(el).fontSize) * 1.2;      // an empty field still takes a line
    }
    return r.left < page.left - SLACK || r.top < page.top - SLACK
      || right > page.right + SLACK || bottom > page.bottom + SLACK;
  }

  function startOffPageCheck() {
    const canvas = document.getElementById('ppCanvas');
    if (!canvas) return;
    const bar = document.createElement('div');
    bar.id = 'ppOffPage';
    bar.className = 'pp-off-page screen-only';
    bar.setAttribute('role', 'status');
    document.body.appendChild(bar);

    function check() {
      const c = canvas.getBoundingClientRect();
      const left = c.left + canvas.clientLeft, top = c.top + canvas.clientTop;
      const page = { left: left, top: top, right: left + canvas.clientWidth, bottom: top + canvas.clientHeight };
      const off = [];
      canvas.querySelectorAll(TARGETS).forEach((el) => {
        if (isOff(el, page)) {
          off.push(labelOf(el));
          if (!el.hasAttribute('data-pp-off')) el.setAttribute('data-pp-off', '');
        } else if (el.hasAttribute('data-pp-off')) {
          el.removeAttribute('data-pp-off');
        }
      });
      const n = off.length;
      const text = n ? n + (n === 1 ? ' field is' : ' fields are') + ' off the page: ' + off.join(', ')
        + ' — drag ' + (n === 1 ? 'it' : 'them') + ' in.' : '';
      if (bar.textContent !== text) bar.textContent = text;     // a status region: announce changes only
      bar.classList.toggle('pp-show', n > 0);
    }

    let queued = false;
    function schedule() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; check(); });
    }
    // data-pp-off is not watched, so marking a field does not re-run the check.
    new MutationObserver(schedule).observe(canvas, {
      attributes: true, attributeFilter: ['style', 'class'], childList: true, subtree: true, characterData: true });
    window.addEventListener('load', schedule);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);
    schedule();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', startOffPageCheck);
  else startOffPageCheck();
})();
