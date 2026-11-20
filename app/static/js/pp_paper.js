/* Custom paper size (RICL-1 A) and whole-page shift (RICL-2 A) for every pre-printed designer and the cheque.
 *
 * The page renders these controls from templates/_pp_paper_extra.html, right after the paper picker. Each designer
 * already resizes the canvas and rewrites the @page rule from the selected <option>'s data-w / data-h / data-css when
 * the picker changes; this script keeps the "Custom size" option's data in step with the W x H boxes and re-fires
 * that change, so no designer needs its own custom-size code. The shift rewrites the print-only translate live.
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
    shiftStyle.textContent = '@media print { #ppCanvas { transform: translate(' + s.x + 'mm, ' + s.y + 'mm); } }';
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
})();
