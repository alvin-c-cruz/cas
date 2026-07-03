(function () {
  function num(v) { return parseFloat((v || '').toString().replace(/,/g, '')) || 0; }

  function recalc() {
    var d = 0, c = 0;
    document.querySelectorAll('#ob-lines .ob-line').forEach(function (row) {
      d += num(row.querySelector('.ob-debit').value);
      c += num(row.querySelector('.ob-credit').value);
    });
    var diff = d - c;
    document.getElementById('ob-total-debit').textContent = amtFmt(d);
    document.getElementById('ob-total-credit').textContent = amtFmt(c);
    document.getElementById('ob-diff').textContent = amtFmt(diff);
    var post = document.getElementById('ob-post');
    if (post) { post.disabled = Math.abs(diff) > 0.001 || d <= 0; }
  }

  // Focus: show a plain, comma-free number and select it for easy overwrite.
  function obAmtFocus(el) {
    var n = num(el.value);
    el.value = n > 0 ? String(n) : '';
    el.select();
  }

  // Format only (no side effects) — used to normalise server-rendered values on load.
  function obFormat(el) {
    var n = num(el.value);
    el.value = n > 0 ? amtFmt(n) : '';
  }

  // Blur: format this field; if it now holds an amount, clear the sibling so the row
  // is Debit XOR Credit; then recompute totals.
  function obBlur(el, siblingSel) {
    var n = num(el.value);
    el.value = n > 0 ? amtFmt(n) : '';
    if (n > 0) {
      var sib = el.closest('.ob-line').querySelector(siblingSel);
      if (sib) { sib.value = ''; }
    }
    recalc();
  }

  function wireRow(row) {
    var acct = row.querySelector('.ob-account');
    if (acct && !acct.disabled && typeof initSearchSelect === 'function'
        && !acct.closest('.choices')) {
      initSearchSelect(acct);
    }
    var deb = row.querySelector('.ob-debit');
    var cred = row.querySelector('.ob-credit');
    if (deb && !deb.disabled) {
      deb.addEventListener('focus', function () { obAmtFocus(deb); });
      deb.addEventListener('blur', function () { obBlur(deb, '.ob-credit'); });
    }
    if (cred && !cred.disabled) {
      cred.addEventListener('focus', function () { obAmtFocus(cred); });
      cred.addEventListener('blur', function () { obBlur(cred, '.ob-debit'); });
    }
    var rm = row.querySelector('.ob-remove');
    if (rm) { rm.addEventListener('click', function () { row.remove(); recalc(); }); }
  }

  var addBtn = document.getElementById('ob-add-row');
  var tpl = document.getElementById('ob-row-template');
  if (addBtn && tpl) {
    addBtn.addEventListener('click', function () {
      var body = document.querySelector('#ob-lines tbody');
      body.appendChild(tpl.content.cloneNode(true));
      var rows = body.querySelectorAll('.ob-line');
      wireRow(rows[rows.length - 1]);
      recalc();
    });
  }

  // Upgrade server-rendered rows: normalise existing amounts, init pickers, wire events.
  document.querySelectorAll('#ob-lines .ob-line').forEach(function (row) {
    var deb = row.querySelector('.ob-debit');
    var cred = row.querySelector('.ob-credit');
    if (deb) { obFormat(deb); }
    if (cred) { obFormat(cred); }
    wireRow(row);
  });
  recalc();

  var fOpen = document.getElementById('ob-finalize-open');
  var fModal = document.getElementById('ob-finalize-modal');
  var fCancel = document.getElementById('ob-finalize-cancel');
  if (fOpen && fModal) { fOpen.addEventListener('click', function () { fModal.hidden = false; }); }
  if (fCancel && fModal) { fCancel.addEventListener('click', function () { fModal.hidden = true; }); }
})();
