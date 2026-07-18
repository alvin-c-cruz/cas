// Recomputes each row's Annual Total live as budget cells are edited.
(function () {
  document.querySelectorAll('.budget-grid-leaf').forEach(function (row) {
    var cells = row.querySelectorAll('.budget-cell');
    var total = row.querySelector('.budget-row-total');
    if (!total) return;

    function recompute() {
      var sum = 0;
      cells.forEach(function (c) {
        var v = parseFloat((c.value || '0').replace(/,/g, ''));
        if (!isNaN(v)) sum += v;
      });
      total.textContent = sum.toFixed(2);
    }

    cells.forEach(function (c) { c.addEventListener('input', recompute); });
  });
})();
