/* SI pre-printed layout designer (SI-P-71) — the thin drag/serialize/save layer.
   Positioning is drag-only. Columns: drag a header left/right to reorder; a checkbox
   strip toggles show/hide. Serializes the DOM to the layout JSON and POSTs it. */
(function () {
  const canvas = document.getElementById('ppCanvas');
  const editBtn = document.getElementById('editLayoutBtn');
  if (!canvas || !editBtn) return;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const fontSel = document.getElementById('ppFontFamily');
  const colStrip = document.getElementById('ppColControls');
  let editing = false;

  // --- Save button injected next to Edit ---
  const saveBtn = document.createElement('button');
  saveBtn.id = 'saveLayoutBtn';
  saveBtn.type = 'button';
  saveBtn.className = 'btn btn-edit';
  saveBtn.textContent = 'Save Layout';
  saveBtn.style.display = 'none';
  editBtn.after(saveBtn);

  const li = () => canvas.querySelector('.pp-lineitems');

  // --- Column show/hide control strip (built once) ---
  function setColVisible(key, visible) {
    canvas.querySelectorAll('.pp-lineitems [data-col="' + key + '"]').forEach((c) =>
      c.classList.toggle('pp-col-hidden', !visible));
  }
  function buildColControls() {
    if (!colStrip || colStrip.dataset.built) return;
    li().querySelectorAll('thead th').forEach((th) => {
      const key = th.dataset.col;
      const label = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.coltoggle = key;
      cb.checked = !th.classList.contains('pp-col-hidden');
      cb.addEventListener('change', () => setColVisible(key, cb.checked));
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + th.textContent.trim()));
      colStrip.appendChild(label);
    });
    colStrip.dataset.built = '1';
  }

  function setEditing(on) {
    editing = on;
    canvas.classList.toggle('pp-editing', editing);
    saveBtn.style.display = editing ? '' : 'none';
    if (fontSel) fontSel.style.display = editing ? '' : 'none';
    if (colStrip) { buildColControls(); colStrip.classList.toggle('pp-show', editing); }
    editBtn.textContent = editing ? 'Exit Edit' : 'Edit Layout';
  }
  editBtn.addEventListener('click', () => setEditing(!editing));

  // --- Column reorder: drag a header across its neighbours ---
  function moveColumn(srcKey, refKey) {
    const rows = [li().querySelector('thead tr'), ...li().querySelectorAll('tbody tr')];
    rows.forEach((row) => {
      const src = row.querySelector('[data-col="' + srcKey + '"]');
      const ref = row.querySelector('[data-col="' + refKey + '"]');
      if (!src || !ref) return;
      const cells = [...row.children];
      if (cells.indexOf(src) < cells.indexOf(ref)) ref.after(src);
      else ref.before(src);
    });
  }

  // --- Element drag + column-reorder drag share the pointer stream ---
  let drag = null;      // moving a .pp-el
  let colDrag = null;   // reordering a column

  canvas.addEventListener('pointerdown', (e) => {
    if (!editing) return;
    const th = e.target.closest('.pp-lineitems thead th');
    if (th) {
      colDrag = { key: th.dataset.col };
      canvas.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    const el = e.target.closest('.pp-el');
    if (!el) return;
    const r = el.getBoundingClientRect();
    const c = canvas.getBoundingClientRect();
    drag = { el, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
    canvas.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  canvas.addEventListener('pointermove', (e) => {
    if (colDrag) {
      const target = [...li().querySelectorAll('thead th')].find((h) => {
        if (h.dataset.col === colDrag.key) return false;
        const r = h.getBoundingClientRect();
        return e.clientX >= r.left && e.clientX <= r.right;
      });
      if (target) moveColumn(colDrag.key, target.dataset.col);
      return;
    }
    if (!drag) return;
    let x = e.clientX - drag.c.left - drag.dx;
    let y = e.clientY - drag.c.top - drag.dy;
    x = Math.max(0, Math.min(canvas.clientWidth, Math.round(x)));
    y = Math.max(0, Math.min(canvas.clientHeight, Math.round(y)));
    drag.el.style.left = x + 'px';
    drag.el.style.top = y + 'px';
  });

  function endDrag() { drag = null; colDrag = null; }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  // --- Serialize DOM -> layout JSON ---
  function collect() {
    const fields = {};
    canvas.querySelectorAll('.pp-el:not(.pp-lineitems)').forEach((el) => {
      const cs = getComputedStyle(el);
      fields[el.dataset.el] = {
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 11,
        bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
      };
    });
    const block = li();
    const columns = [...block.querySelectorAll('thead th')].map((th) => ({
      key: th.dataset.col,
      visible: !th.classList.contains('pp-col-hidden'),
      width: parseInt(th.style.width) || 60,
    }));
    const lics = getComputedStyle(block);
    return {
      page: { fontFamily: getComputedStyle(document.body).fontFamily },
      fields,
      lineItems: {
        x: parseInt(block.style.left) || 0,
        y: parseInt(block.style.top) || 0,
        width: parseInt(block.style.width) || 714,
        fontSize: parseInt(lics.fontSize) || 10,
        bold: lics.fontWeight === '700' || lics.fontWeight === 'bold',
        columns,
      },
    };
  }

  saveBtn.addEventListener('click', async () => {
    saveBtn.textContent = 'Saving…';
    try {
      const resp = await fetch('/sales-invoices/print-layout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify(collect()),
      });
      if (resp.ok) {
        if (!document.getElementById('layoutSavedFlag')) {
          const flag = document.createElement('span');
          flag.id = 'layoutSavedFlag';
          flag.style.display = 'none';
          document.body.appendChild(flag);
        }
        saveBtn.textContent = 'Saved ✓';
        setTimeout(() => { saveBtn.textContent = 'Save Layout'; }, 1500);
      } else {
        saveBtn.textContent = 'Save failed';
      }
    } catch (err) {
      saveBtn.textContent = 'Save failed';
    }
  });

  // page-wide font family (options rendered server-side from ALLOWED_FONTS)
  if (fontSel) {
    fontSel.addEventListener('change', () => {
      document.body.style.fontFamily = fontSel.value;
    });
  }
})();
