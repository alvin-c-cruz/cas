(function () {
  function num(v) { return parseFloat((v || '').toString().replace(/,/g, '')) || 0; }

  function recalc() {
    var d = 0, c = 0;
    document.querySelectorAll('#ob-lines .ob-line').forEach(function (row) {
      d += num(row.querySelector('.ob-debit').value);
      c += num(row.querySelector('.ob-credit').value);
    });
    var diff = d - c;
    document.getElementById('ob-total-debit').textContent = d.toFixed(2);
    document.getElementById('ob-total-credit').textContent = c.toFixed(2);
    document.getElementById('ob-diff').textContent = diff.toFixed(2);
    var post = document.getElementById('ob-post');
    if (post) { post.disabled = Math.abs(diff) > 0.001 || d <= 0; }
  }

  function wireRow(row) {
    row.querySelectorAll('.ob-debit, .ob-credit').forEach(function (inp) {
      inp.addEventListener('input', recalc);
    });
    var rm = row.querySelector('.ob-remove');
    if (rm) { rm.addEventListener('click', function () { row.remove(); recalc(); }); }
  }

  var addBtn = document.getElementById('ob-add-row');
  if (addBtn) {
    addBtn.addEventListener('click', function () {
      var body = document.querySelector('#ob-lines tbody');
      var first = body.querySelector('.ob-line');
      var clone;
      if (first) {
        clone = first.cloneNode(true);
        clone.querySelectorAll('input').forEach(function (i) { i.value = ''; });
        // cloneNode copies the <select>'s selection — reset so a new line starts unselected.
        clone.querySelectorAll('select').forEach(function (s) { s.selectedIndex = 0; });
      } else {
        return; // server always renders at least one template row when editable
      }
      body.appendChild(clone);
      wireRow(clone);
      recalc();
    });
  }

  document.querySelectorAll('#ob-lines .ob-line').forEach(wireRow);
  recalc();

  var fOpen = document.getElementById('ob-finalize-open');
  var fModal = document.getElementById('ob-finalize-modal');
  var fCancel = document.getElementById('ob-finalize-cancel');
  if (fOpen && fModal) { fOpen.addEventListener('click', function () { fModal.hidden = false; }); }
  if (fCancel && fModal) { fCancel.addEventListener('click', function () { fModal.hidden = true; }); }
})();
