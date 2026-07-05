/* SI pre-printed layout designer (SI-P-71) — the thin drag/serialize/save layer.
   Positioning is drag-only; the only control inputs are fonts (Task 6) and column
   show/hide (Task 5). Serializes the DOM to the layout JSON and POSTs it. */
(function () {
  const canvas = document.getElementById('ppCanvas');
  const editBtn = document.getElementById('editLayoutBtn');
  if (!canvas || !editBtn) return;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  let editing = false;

  // --- Save button injected next to Edit ---
  const saveBtn = document.createElement('button');
  saveBtn.id = 'saveLayoutBtn';
  saveBtn.type = 'button';
  saveBtn.className = 'btn btn-edit';
  saveBtn.textContent = 'Save Layout';
  saveBtn.style.display = 'none';
  editBtn.after(saveBtn);

  const fontSel = document.getElementById('ppFontFamily');

  function setEditing(on) {
    editing = on;
    canvas.classList.toggle('pp-editing', editing);
    saveBtn.style.display = editing ? '' : 'none';
    if (fontSel) fontSel.style.display = editing ? '' : 'none';
    editBtn.textContent = editing ? 'Exit Edit' : 'Edit Layout';
    document.dispatchEvent(new CustomEvent('pp-edit-toggle', { detail: { editing } }));
  }
  editBtn.addEventListener('click', () => setEditing(!editing));

  // --- Drag any .pp-el while editing ---
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => {
    if (!editing) return;
    const el = e.target.closest('.pp-el');
    if (!el) return;
    const r = el.getBoundingClientRect();
    const c = canvas.getBoundingClientRect();
    drag = { el, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
    el.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    let x = e.clientX - drag.c.left - drag.dx;
    let y = e.clientY - drag.c.top - drag.dy;
    x = Math.max(0, Math.min(canvas.clientWidth, Math.round(x)));
    y = Math.max(0, Math.min(canvas.clientHeight, Math.round(y)));
    drag.el.style.left = x + 'px';
    drag.el.style.top = y + 'px';
  });
  function endDrag() { drag = null; }
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
    const li = canvas.querySelector('.pp-lineitems');
    const columns = [...li.querySelectorAll('thead th')].map((th) => ({
      key: th.dataset.col, visible: true, width: parseInt(th.style.width) || 60,
    }));
    (li.dataset.hidden || '').split(',').filter(Boolean).forEach((k) =>
      columns.push({ key: k, visible: false, width: 60 }));
    const lics = getComputedStyle(li);
    return {
      page: { fontFamily: getComputedStyle(document.body).fontFamily },
      fields,
      lineItems: {
        x: parseInt(li.style.left) || 0,
        y: parseInt(li.style.top) || 0,
        width: parseInt(li.style.width) || 714,
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

  // page-wide font family (populated server-side from ALLOWED_FONTS)
  if (fontSel) {
    fontSel.addEventListener('change', () => {
      document.body.style.fontFamily = fontSel.value;
    });
  }
})();
