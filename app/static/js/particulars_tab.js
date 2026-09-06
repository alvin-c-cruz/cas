/* Tab types a TAB in the Notes (Particulars) box, on any form that has one.

   The goal is a small tally typed into Particulars whose figures line up in a column
   (owner, 2026-09-06). Two things carry that on the printed voucher, and neither is this
   file: the pre-printed face renders the value `white-space: pre`, so runs of whitespace
   survive, and the layout font is monospace, so equal character counts are equal widths.
   A tab is simply far fewer keystrokes than counting spaces.

   Shared by the APV and CDV forms rather than pasted into both -- the same reasoning as
   preprinted_je_designer.js. Self-initialising: it binds to `textarea[name="notes"]`,
   the selector those forms' own scripts already use, and does nothing on a page without
   one.

   KEYBOARD TRAP: capturing Tab inside a textarea means it no longer moves focus, which
   strands anyone navigating by keyboard. Two ways out stay open, so the field is never a
   dead end:
     * Shift+Tab still moves focus backward (never captured).
     * Escape arms a one-shot pass -- the NEXT Tab moves focus forward as usual. */
(function () {
  var box = document.querySelector('textarea[name="notes"]');
  if (!box) return;
  var letNextTabEscape = false;

  box.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      letNextTabEscape = true;             // the NEXT Tab moves focus instead
      return;
    }
    if (e.key !== 'Tab') {
      // Any other key disarms, so Escape cannot linger and silently swallow a tab the
      // user meant to type minutes later.
      letNextTabEscape = false;
      return;
    }
    if (e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;
    if (letNextTabEscape) {
      letNextTabEscape = false;
      return;                              // fall through to the browser: move focus
    }
    e.preventDefault();
    var start = box.selectionStart, end = box.selectionEnd;
    // setRangeText keeps the browser's native undo stack; assigning box.value wholesale
    // discards it, so a mistyped tab could not be taken back with Ctrl+Z.
    if (box.setRangeText) {
      box.setRangeText('\t', start, end, 'end');
    } else {
      box.value = box.value.slice(0, start) + '\t' + box.value.slice(end);
      box.selectionStart = box.selectionEnd = start + 1;
    }
    box.dispatchEvent(new Event('input', { bubbles: true }));   // keep listeners honest
  });
})();
