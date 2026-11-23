/* B5-W A (owner, 23 Nov 2026): a DR number typed lower than the last one gets a hint beside DR #:
   "Lower than the last DR number, 0275 — fine if it is the paper's number". Saving still goes through: a paper DR pad
   can run behind the numbers already entered. A number equal to an existing DR is refused on saving, as before.
   The page renders #dr-number-hint (with the last number) only on a new DR that has a numbered one before it.
   Plain numbers only, compared by value ("264" is lower than "0275"); anything else gets no hint. */
(function () {
  'use strict';
  var hint = document.getElementById('dr-number-hint');
  var box = document.getElementById('dr_number');
  if (!hint || !box) { return; }
  var last = hint.getAttribute('data-last') || '';

  function value(digits) { return digits.replace(/^0+/, '') || '0'; }
  function lower(a, b) {        // a < b, both plain digit strings, any length
    var x = value(a), y = value(b);
    return x.length !== y.length ? x.length < y.length : x < y;
  }

  function check() {
    var typed = box.value.trim();
    var show = /^\d+$/.test(typed) && /^\d+$/.test(last) && lower(typed, last);
    var text = show ? 'Lower than the last DR number, ' + last + " — fine if it is the paper's number" : '';
    if (hint.textContent !== text) { hint.textContent = text; }
    hint.style.display = show ? '' : 'none';
  }

  box.addEventListener('input', check);
  check();
})();
