/* Payslip pre-printed layout designer (R-06 Payslips) — the thin drag/serialize/save
   layer. Positioning is drag-only. A payslip has no line-item grid, so this is purely
   free-standing fields + editable signature texts. Serializes the DOM to the layout
   JSON and POSTs it. */
(function () {
  const canvas = document.getElementById('ppCanvas');
  const editBtn = document.getElementById('editLayoutBtn');
  if (!canvas || !editBtn) return;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const fontSel = document.getElementById('ppFontFamily');
  const paperSel = document.getElementById('ppPaper');
  const dateSel = document.getElementById('ppDateFormat');
  const fieldStrip = document.getElementById('ppFieldControls');
  const printBtn = document.querySelector('.btn-print');
  let editing = false;

  // --- Save button injected next to Edit ---
  const saveBtn = document.createElement('button');
  saveBtn.id = 'saveLayoutBtn';
  saveBtn.type = 'button';
  saveBtn.className = 'btn btn-edit';
  saveBtn.textContent = 'Save Layout';
  saveBtn.style.display = 'none';
  editBtn.after(saveBtn);

  // --- "+ Add text" button (arbitrary layout text) injected next to Save ---
  const addTextBtn = document.createElement('button');
  addTextBtn.id = 'addTextBtn';
  addTextBtn.type = 'button';
  addTextBtn.className = 'btn btn-edit';
  addTextBtn.textContent = '+ Add text';
  addTextBtn.style.display = 'none';
  saveBtn.after(addTextBtn);

  // --- Non-blocking notice banner (never confirm()/alert()) ---
  function showNotice(msg) {
    let n = document.getElementById('ppNotice');
    if (!n) {
      n = document.createElement('div');
      n.id = 'ppNotice';
      n.className = 'pp-notice screen-only';
      document.body.appendChild(n);
    }
    n.textContent = msg;
    n.style.display = 'block';
    clearTimeout(n._t);
    n._t = setTimeout(() => { n.style.display = 'none'; }, 4000);
  }

  // --- Floating per-element toolbar: font size -/+ and bold ---
  const elBar = document.createElement('div');
  elBar.id = 'ppElemBar';
  elBar.className = 'pp-elem-bar screen-only';
  elBar.style.display = 'none';
  elBar.innerHTML =
    '<button type="button" id="ppFontDec" title="Smaller">A-</button>' +
    '<button type="button" id="ppFontInc" title="Larger">A+</button>' +
    '<button type="button" id="ppBoldBtn" title="Bold"><b>B</b></button>' +
    '<button type="button" id="ppDupBtn" title="Duplicate">Dup</button>' +
    '<button type="button" id="ppDelBtn" title="Delete copy">Del</button>' +
    '<input type="text" id="ppTextInput" title="Edit text" style="display:none;width:170px;">';
  document.body.appendChild(elBar);
  const textInput = elBar.querySelector('#ppTextInput');
  // Editing a layout text -> live-update its content.
  textInput.addEventListener('input', () => {
    if (selected && selected.classList.contains('pp-text')) selected.textContent = textInput.value;
  });
  // Don't let a drag start from inside the text input.
  textInput.addEventListener('pointerdown', (e) => e.stopPropagation());
  let selected = null;

  function positionBar() {
    if (!selected) return;
    const r = selected.getBoundingClientRect();
    elBar.style.left = (window.scrollX + r.left) + 'px';
    elBar.style.top = Math.max(0, window.scrollY + r.top - 32) + 'px';
  }
  function selectEl(el) {
    if (selected) selected.classList.remove('pp-selected');
    selected = el;
    if (!el) { elBar.style.display = 'none'; return; }
    el.classList.add('pp-selected');
    elBar.style.display = 'flex';
    // Only duplicated copies are deletable; primary fields use the Fields checklist.
    const delBtn = elBar.querySelector('#ppDelBtn');
    // Deletable: duplicated field copies AND any layout text (signatory or added).
    if (delBtn) delBtn.style.display = (el.dataset.extra || el.classList.contains('pp-text')) ? '' : 'none';
    // Layout texts are not duplicable.
    const isText = el.classList.contains('pp-text');
    const dupBtn = elBar.querySelector('#ppDupBtn');
    if (dupBtn) dupBtn.style.display = isText ? 'none' : '';
    // Layout texts get an editable text box in the toolbar.
    textInput.style.display = isText ? '' : 'none';
    if (isText) textInput.value = el.textContent;
    positionBar();
  }
  function duplicateSelected() {
    if (!selected) return;
    const clone = selected.cloneNode(true);
    clone.classList.remove('pp-selected', 'pp-field-hidden');
    clone.dataset.extra = '1';
    clone.style.left = ((parseInt(selected.style.left) || 0) + 16) + 'px';
    clone.style.top = ((parseInt(selected.style.top) || 0) + 16) + 'px';
    canvas.appendChild(clone);
    selectEl(clone);
  }
  function deleteSelected() {
    if (!selected) return;
    const isText = selected.classList.contains('pp-text');
    if (!selected.dataset.extra && !isText) return;     // copies + layout texts only
    // Warn (don't block) when a pre-printed signatory line is removed.
    if (isText && selected.dataset.signatory) {
      showNotice('Removed signatory line "' + (selected.textContent || '').trim() +
        '". The blank-form default still ships it.');
    }
    const el = selected;
    selectEl(null);
    el.remove();
  }
  function fontTargets() {
    return [selected];
  }
  function changeFont(delta) {
    if (!selected) return;
    fontTargets().forEach((el) => {
      const cur = parseInt(getComputedStyle(el).fontSize) || 11;
      el.style.fontSize = Math.max(6, Math.min(72, cur + delta)) + 'px';
    });
    positionBar();
  }
  elBar.querySelector('#ppFontInc').addEventListener('click', () => changeFont(1));
  elBar.querySelector('#ppFontDec').addEventListener('click', () => changeFont(-1));
  elBar.querySelector('#ppBoldBtn').addEventListener('click', () => {
    if (!selected) return;
    const bold = ['700', 'bold'].includes(getComputedStyle(selected).fontWeight);
    fontTargets().forEach((el) => { el.style.fontWeight = bold ? 'normal' : 'bold'; });
  });
  elBar.querySelector('#ppDupBtn').addEventListener('click', duplicateSelected);
  elBar.querySelector('#ppDelBtn').addEventListener('click', deleteSelected);

  const fieldEls = () => [...canvas.querySelectorAll('.pp-el:not([data-extra])')];

  function stripHeading(text) {
    const h = document.createElement('span');
    h.textContent = text;
    h.style.fontWeight = '700';
    return h;
  }

  // --- Per-field show/hide control strip (built once) ---
  function setFieldVisible(key, visible) {
    const el = canvas.querySelector('[data-el="' + key + '"], [data-text="' + key + '"]');
    if (el) el.classList.toggle('pp-field-hidden', !visible);
  }
  function buildFieldControls() {
    if (!fieldStrip || fieldStrip.dataset.built) return;
    fieldStrip.appendChild(stripHeading('Fields:'));
    fieldEls().forEach((el) => {
      const key = el.dataset.el || el.dataset.text;
      const label = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.fieldtoggle = key;
      cb.checked = !el.classList.contains('pp-field-hidden');
      cb.addEventListener('change', () => setFieldVisible(key, cb.checked));
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + (el.dataset.label || key)));
      fieldStrip.appendChild(label);
    });
    fieldStrip.dataset.built = '1';
  }

  function setEditing(on) {
    editing = on;
    canvas.classList.toggle('pp-editing', editing);
    saveBtn.style.display = editing ? '' : 'none';
    addTextBtn.style.display = editing ? '' : 'none';
    if (fontSel) fontSel.style.display = editing ? '' : 'none';
    if (paperSel) paperSel.style.display = editing ? '' : 'none';
    if (dateSel) dateSel.style.display = editing ? '' : 'none';
    if (printBtn) printBtn.style.display = editing ? 'none' : '';  // no printing while designing
    if (fieldStrip) { buildFieldControls(); fieldStrip.classList.toggle('pp-show', editing); }
    editBtn.textContent = editing ? 'Exit Edit' : 'Edit Layout';
    if (!editing) selectEl(null);
  }
  editBtn.addEventListener('click', () => setEditing(!editing));

  // --- Drag: fields (.pp-el) move freely. Cells/rows never move independently. ---
  let drag = null;       // moving a .pp-el

  canvas.addEventListener('pointerdown', (e) => {
    if (!editing) return;
    if (e.target.isContentEditable) return;    // let inline text editing happen
    const c = canvas.getBoundingClientRect();
    const el = e.target.closest('.pp-el');
    if (!el) return;
    selectEl(el);
    const r = el.getBoundingClientRect();
    drag = { el, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
    canvas.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const x = Math.max(0, Math.min(canvas.clientWidth, Math.round(e.clientX - drag.c.left - drag.dx)));
    const y = Math.max(0, Math.min(canvas.clientHeight, Math.round(e.clientY - drag.c.top - drag.dy)));
    drag.el.style.left = x + 'px';
    drag.el.style.top = y + 'px';
  });

  function endDrag() { drag = null; positionBar(); }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  // --- Serialize DOM -> layout JSON ---
  function collect() {
    const fields = {};
    canvas.querySelectorAll('.pp-el:not([data-extra]):not(.pp-text)').forEach((el) => {
      const cs = getComputedStyle(el);
      fields[el.dataset.el] = {
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 11,
        bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
        hidden: el.classList.contains('pp-field-hidden'),
      };
    });
    const extras = [...canvas.querySelectorAll('.pp-el[data-extra]')].map((el) => {
      const cs = getComputedStyle(el);
      return {
        key: el.dataset.el,
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 11,
        bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
      };
    });
    const texts = [...canvas.querySelectorAll('.pp-text')].map((el) => {
      const cs = getComputedStyle(el);
      return {
        id: el.dataset.text,
        text: el.textContent,
        x: parseInt(el.style.left) || 0,
        y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 10,
        bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
        hidden: el.classList.contains('pp-field-hidden'),
      };
    });
    return {
      paper: (paperSel && paperSel.value) || document.body.dataset.paper || 'continuous',
      dateFormat: (dateSel && dateSel.value) || 'long',
      extras,
      texts,
      // read the select (exact ALLOWED_FONTS string) rather than the computed
      // stack, so the value round-trips through the server-side whitelist.
      page: { fontFamily: (fontSel && fontSel.value) || getComputedStyle(document.body).fontFamily },
      fields,
    };
  }

  saveBtn.addEventListener('click', async () => {
    saveBtn.textContent = 'Saving…';
    try {
      const resp = await fetch('/payroll/payslip-print-layout', {
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

  // --- "+ Add text": drop a fresh, deletable layout text onto the canvas ---
  let addTextSeq = 0;
  addTextBtn.addEventListener('click', () => {
    const el = document.createElement('div');
    el.className = 'pp-el pp-text';
    el.dataset.text = 'text_' + Date.now() + '_' + (++addTextSeq);
    el.dataset.label = 'New text';
    el.textContent = 'New text';
    el.style.left = '80px';
    el.style.top = '120px';
    el.style.fontSize = '10px';
    el.style.fontWeight = 'normal';
    canvas.appendChild(el);
    selectEl(el);
  });

  // page-wide font family (options rendered server-side from ALLOWED_FONTS)
  if (fontSel) {
    fontSel.addEventListener('change', () => {
      document.body.style.fontFamily = fontSel.value;
    });
  }

  // date format: live-preview the date-hired/pay-date fields. Keys + strftime mirror
  // preprinted_layout.DATE_FORMATS (day/month zero-padded, matching strftime).
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmtDate(iso, key) {
    const p = (iso || '').split('-');
    if (p.length !== 3) return iso || '';
    const y = p[0], m = p[1], d = p[2], mi = parseInt(m, 10) - 1;
    switch (key) {
      case 'long': return d + ' ' + MONTHS[mi] + ' ' + y;
      case 'medium': return MON[mi] + ' ' + d + ', ' + y;
      case 'us': return m + '/' + d + '/' + y;
      case 'eu': return d + '/' + m + '/' + y;
      default: return iso;   // iso
    }
  }
  if (dateSel) {
    dateSel.addEventListener('change', () => {
      canvas.querySelectorAll('.pp-el[data-date]').forEach((el) => {
        el.textContent = fmtDate(el.dataset.date, dateSel.value);
      });
    });
  }

  // paper size: resize the canvas + rewrite the @page rule live; guides hide for non-continuous.
  if (paperSel) {
    paperSel.addEventListener('change', () => {
      const opt = paperSel.selectedOptions[0];
      document.body.dataset.paper = paperSel.value;
      canvas.style.width = opt.dataset.w + 'px';
      canvas.style.height = opt.dataset.h + 'px';
      const ps = document.getElementById('ppPageStyle');
      if (ps) ps.textContent = '@page { size: ' + opt.dataset.css + '; margin: 0; }';
    });
  }
})();
