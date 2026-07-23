// app/static/js/physical_count_entry.js
/* Live variance calc for the Physical Count entry grid. Purely a display
 * convenience -- the server independently recomputes the real posted
 * variance against the CURRENT balance at approve time (see
 * physical_count_service.py::approve_physical_count), so this script never
 * needs to know about costing methods or auto-post eligibility. */
(function () {
  'use strict';

  var table = document.getElementById('pc-entry-table');
  if (!table) { return; }

  function formatQty(n) {
    return n.toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 4});
  }

  function updateRow(row) {
    var bookQty = parseFloat(row.getAttribute('data-book-qty'));
    var input = row.querySelector('.pc-counted-input');
    var cell = row.querySelector('.pc-variance-cell');
    var counted = parseFloat(input.value);
    cell.classList.remove('pc-variance-pos', 'pc-variance-neg');
    if (isNaN(counted)) {
      cell.textContent = '';
      return;
    }
    var variance = counted - bookQty;
    cell.textContent = (variance > 0 ? '+' : '') + formatQty(variance);
    if (variance > 0) { cell.classList.add('pc-variance-pos'); }
    else if (variance < 0) { cell.classList.add('pc-variance-neg'); }
  }

  Array.prototype.forEach.call(table.querySelectorAll('tbody tr'), function (row) {
    var input = row.querySelector('.pc-counted-input');
    input.addEventListener('input', function () { updateRow(row); });
  });
})();
