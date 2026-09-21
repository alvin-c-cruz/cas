/* Shared pre-printed layout designer -- the thin drag/serialize/save layer.
   Positioning is drag-only. Columns: drag a header left/right to reorder; a checkbox
   strip toggles show/hide. Serializes the DOM to the layout JSON and POSTs it.

   ONE designer for every document type that uses app/common/preprinted_base.py.
   The eight existing per-document copies (so/sv/apv/cdv/crv/dr/jv/payslip) are left
   untouched; this file is what a NEW document loads instead of becoming a ninth copy.

   Usage (from the document's print_preprinted.html, inside its can_edit_layout gate):

       <script src=".../preprinted_designer.js?v=1"></script>
       <script>initPreprintedDesigner({ saveUrl: "/purchase-orders/print-layout" });</script>

   config: { saveUrl }  -- the POST endpoint, and nothing else besides `layoutPicker`
   below is REQUIRED; the designer refuses to initialise without saveUrl rather than
   quietly offering an Edit button whose Save cannot work. Everything else the
   designer needs it reads from the DOM the template already renders: labels come
   from each element's own data-label, and edit permission is the template's
   decision (it renders #editLayoutBtn only for an allowed user -- no #editLayoutBtn,
   no designer).

   config.layoutPicker: { saveAsUrl, renameUrl, deleteUrl, selectUrl, branchId } --
   OPTIONAL. Named print layouts (currently Purchase Orders only -- see
   .superpowers/sdd/2026-09-18-named-print-layouts-plan/). Wiring is a no-op unless
   BOTH this config key AND the template's #ppLayoutPicker <select> are present, so
   PR/RR (which share this file but not named layouts yet) are unaffected. Decision 3
   of that plan: picking a layout here only changes what is being EDITED on this
   canvas -- it must NEVER repoint this workstation. Only #ppUseHereBtn does that.

   Element ids are the contract with the template and with every existing e2e
   selector: editLayoutBtn, layoutSavedFlag, ppCanvas, ppColControls, ppDateFormat,
   ppFieldControls, ppFontFamily, ppNotice, ppPageStyle, ppPaper, ppBoldBtn, ppDelBtn,
   ppDupBtn, ppFontDec, ppFontInc, ppTextInput, ppLayoutPicker, ppDeviceLayout,
   ppSaveAsBtn, ppRenameBtn, ppDeleteLayoutBtn, ppUseHereBtn. Do not rename any of
   them. */
(function (global) {
  'use strict';

  // Mirrors app/common/preprinted_base.py. The server sanitises every saved layout
  // against these, so clamping to the same numbers here keeps what is dragged and
  // what is stored the same thing (drag a field to x=10 without this and it silently
  // jumps to x=48 on the next page load).
  var SAFE_MARGIN = 48;          // printable inset (tractor-feed margin)
  var CANVAS_H = 1008;           // preprinted_base.CANVAS_H -- the server's y ceiling
  var FONT_MIN = 6, FONT_MAX = 72;
  var COL_WIDTH_MIN = 20;        // narrowest a line-item column may be dragged

  function initPreprintedDesigner(config) {
    const cfg = config || {};
    const canvas = document.getElementById('ppCanvas');
    const editBtn = document.getElementById('editLayoutBtn');
    if (!canvas || !editBtn) return false;
    // This is a GLOBAL function, so a template can call it twice (the old per-document
    // IIFE could only ever run once). A second run would inject a second
    // #saveLayoutBtn / #addTextBtn / #ppElemBar -- duplicate ids that the toolbar
    // wiring and every e2e selector rely on being unique.
    if (canvas.dataset.ppInit) return false;

    // --- Non-blocking notice banner (never confirm()/alert()) ---
    // Declared before the guards below so a refusal can still tell the user.
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

    if (!cfg.saveUrl) {
      // Fail closed: an unconfigured designer would let a user rearrange a whole
      // form and then lose it on Save. But the template has already rendered the
      // Edit button, so ALSO disable it and say why -- a silent console.error
      // leaves the user clicking a dead control with no explanation.
      if (global.console) console.error('initPreprintedDesigner: config.saveUrl is required');
      editBtn.disabled = true;
      editBtn.title = 'Layout editing is unavailable on this page.';
      showNotice('Layout editing is unavailable on this page.');
      return false;
    }
    const saveUrl = cfg.saveUrl;
    const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const fontSel = document.getElementById('ppFontFamily');
    const paperSel = document.getElementById('ppPaper');
    const dateSel = document.getElementById('ppDateFormat');
    const fieldStrip = document.getElementById('ppFieldControls');
    const colStrip = document.getElementById('ppColControls');
    const printBtn = document.querySelector('.btn-print');
    let editing = false;

    // --- Position clamps (see SAFE_MARGIN above) ---
    // Fields AND line-item columns clamp x IDENTICALLY, inside the safe margin:
    // SAFE_MARGIN..canvasWidth - SAFE_MARGIN, matching BOTH preprinted_base._clean_box
    // and _clean_columns.
    // There used to be an asymmetry here: a COLUMN clamped to the bare canvas
    // (0..canvasWidth), mirroring the server's own looser _clean_columns bound, so a
    // column could be dragged onto the tractor-feed perforations and the server would
    // PERSIST it there -- while a field dragged to the same point was pulled back to
    // the margin. Both sides were tightened to the field bound on 2026-08-15 (owner
    // decision: tighten the server rather than loosen the client, so what is dragged
    // is what is stored). The asymmetry was REMOVED DELIBERATELY -- it was not lost in
    // an edit. The two names are kept so the call sites still read "field" vs "column",
    // but they are ONE clamp now and must stay that way.
    function clampFieldX(x) {
      return Math.max(SAFE_MARGIN, Math.min(canvas.clientWidth - SAFE_MARGIN, x));
    }
    // y clamps to the CONSTANT 1008, NOT to canvas.clientHeight. The two are the same
    // number on continuous stock, but Letter makes the canvas 1056px tall
    // (preprinted_base.PAPER_SIZES) while _clean_box still clamps y to CANVAS_H = 1008.
    // Reading the live canvas height there let a user drag po_no to y=1050 on Letter and
    // get 1008 back on the next load -- a silent 42px upward jump, the same defect class
    // the x-axis fix (7c7dfd1d) removed. lineItems.y and text blocks share this clamp,
    // so all three moved together. Do not "simplify" this back to canvas.clientHeight.
    function clampY(y) {
      return Math.max(0, Math.min(CANVAS_H, y));
    }
    function clampColX(x) {
      return clampFieldX(x);
    }

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
      // Layout texts and line-item columns are not duplicable.
      const isText = el.classList.contains('pp-text');
      const dupBtn = elBar.querySelector('#ppDupBtn');
      if (dupBtn) dupBtn.style.display = (isText || el.classList.contains('pp-col')) ? 'none' : '';
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
      // Offset the copy so it is grabbable, but never outside the printable area.
      clone.style.left = clampFieldX((parseInt(selected.style.left) || 0) + 16) + 'px';
      clone.style.top = clampY((parseInt(selected.style.top) || 0) + 16) + 'px';
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
    // A line-item column shares the band font, so font changes apply to every column.
    function fontTargets() {
      return (selected && selected.classList.contains('pp-col')) ? cols() : [selected];
    }
    function changeFont(delta) {
      if (!selected) return;
      fontTargets().forEach((el) => {
        const cur = parseInt(getComputedStyle(el).fontSize) || 11;
        el.style.fontSize = Math.max(FONT_MIN, Math.min(FONT_MAX, cur + delta)) + 'px';
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

    const li = () => canvas.querySelector('.pp-lineitems');
    const cols = () => [...canvas.querySelectorAll('.pp-col')];
    const fieldEls = () => [...canvas.querySelectorAll('.pp-el:not(.pp-lineitems):not([data-extra])')];

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
        // The label the user reads is the template's own data-label -- there is no
        // per-document label config; the DOM already carries it.
        label.appendChild(document.createTextNode(' ' + (el.dataset.label || key)));
        fieldStrip.appendChild(label);
      });
      fieldStrip.dataset.built = '1';
    }

    // --- Column show/hide control strip (built once) ---
    function setColVisible(key, visible) {
      canvas.querySelectorAll('.pp-col[data-col="' + key + '"]').forEach((c) =>
        c.classList.toggle('pp-col-hidden', !visible));
    }
    function buildColControls() {
      if (!colStrip || colStrip.dataset.built) return;
      colStrip.appendChild(stripHeading('Columns:'));
      cols().forEach((col) => {
        const key = col.dataset.col;
        const label = document.createElement('label');
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.dataset.coltoggle = key;
        cb.checked = !col.classList.contains('pp-col-hidden');
        cb.addEventListener('change', () => setColVisible(key, cb.checked));
        label.appendChild(cb);
        label.appendChild(document.createTextNode(' ' + (col.dataset.label || key)));
        colStrip.appendChild(label);
      });
      colStrip.dataset.built = '1';
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
      if (colStrip) { buildColControls(); colStrip.classList.toggle('pp-show', editing); }
      editBtn.textContent = editing ? 'Exit Edit' : 'Edit Layout';
      if (!editing) selectEl(null);
    }
    editBtn.addEventListener('click', () => setEditing(!editing));

    // --- Drag: fields (.pp-el) move freely; a line-item column (.pp-col) moves
    //     HORIZONTALLY on its own x, while a VERTICAL drag moves the whole band
    //     (all columns share the top), so rows always stay aligned. Cells/rows never
    //     move independently of their column. ---
    let drag = null;       // moving a .pp-el
    let colDrag = null;    // moving a .pp-col
    let colResize = null;  // resizing a .pp-col width
    const EDGE = 8;        // px hot-zone at a column's right edge = resize handle

    canvas.addEventListener('pointerdown', (e) => {
      if (!editing) return;
      if (e.target.isContentEditable) return;    // let inline text editing happen
      const c = canvas.getBoundingClientRect();
      const col = e.target.closest('.pp-col');
      if (col) {
        selectEl(col);                              // show the font toolbar for the band
        const r = col.getBoundingClientRect();
        if (e.clientX >= r.right - EDGE) {
          // grab the right edge -> resize width
          colResize = { col, startW: parseInt(col.style.width) || Math.round(r.width), startX: e.clientX };
        } else {
          colDrag = { col, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
        }
        canvas.setPointerCapture(e.pointerId);
        e.preventDefault();
        return;
      }
      const el = e.target.closest('.pp-el');
      if (!el) return;
      selectEl(el);
      const r = el.getBoundingClientRect();
      drag = { el, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
      canvas.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    canvas.addEventListener('pointermove', (e) => {
      if (colResize) {
        const w = Math.max(COL_WIDTH_MIN,
          Math.min(canvas.clientWidth, colResize.startW + (e.clientX - colResize.startX)));
        colResize.col.style.width = Math.round(w) + 'px';      // cells follow the column width
        return;
      }
      if (colDrag) {
        const x = clampColX(Math.round(e.clientX - colDrag.c.left - colDrag.dx));
        const y = clampY(Math.round(e.clientY - colDrag.c.top - colDrag.dy));
        colDrag.col.style.left = x + 'px';                     // this column's x
        cols().forEach((c) => { c.style.top = y + 'px'; });    // shared band top -> rows aligned
        return;
      }
      if (!drag) {
        // hover cursor hint: resize near the right edge, move elsewhere
        const hov = e.target.closest && e.target.closest('.pp-col');
        if (hov) {
          const r = hov.getBoundingClientRect();
          hov.style.cursor = (e.clientX >= r.right - EDGE) ? 'ew-resize' : 'move';
        }
        return;
      }
      drag.el.style.left = clampFieldX(Math.round(e.clientX - drag.c.left - drag.dx)) + 'px';
      drag.el.style.top = clampY(Math.round(e.clientY - drag.c.top - drag.dy)) + 'px';
    });

    function endDrag() { drag = null; colDrag = null; colResize = null; positionBar(); }
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);

    // --- Serialize DOM -> layout JSON ---
    // `w` (field width) is sent only when the element carries one. Documents built on
    // preprinted_base give every field its own width; the eight older per-document
    // layouts have no 'w' at all and simply ignore the key.
    function boxWidth(el) {
      const w = parseInt(el.style.width);
      return Number.isFinite(w) ? w : undefined;
    }
    function collect() {
      const fields = {};
      canvas.querySelectorAll('.pp-el:not(.pp-lineitems):not([data-extra]):not(.pp-text)').forEach((el) => {
        const cs = getComputedStyle(el);
        fields[el.dataset.el] = {
          x: parseInt(el.style.left) || 0,
          y: parseInt(el.style.top) || 0,
          w: boxWidth(el),
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
      const colEls = cols();
      const first = colEls[0];
      const lics = first ? getComputedStyle(first) : null;
      const columns = colEls.map((c) => ({
        key: c.dataset.col,
        x: parseInt(c.style.left) || 0,
        visible: !c.classList.contains('pp-col-hidden'),
        width: parseInt(c.style.width) || 60,
      }));
      const band = li();
      return {
        paper: (paperSel && paperSel.value) || document.body.dataset.paper || 'continuous',
        dateFormat: (dateSel && dateSel.value) || 'long',
        extras,
        texts,
        // read the select (exact ALLOWED_FONTS string) rather than the computed
        // stack, so the value round-trips through the server-side whitelist.
        page: { fontFamily: (fontSel && fontSel.value) || getComputedStyle(document.body).fontFamily },
        fields,
        lineItems: {
          y: first ? (parseInt(first.style.top) || 0) : 300,
          // the band is not drawn on every document (e.g. a voucher face)
          rowHeight: (band && parseInt(band.dataset.rowheight)) || 20,
          fontSize: lics ? (parseInt(lics.fontSize) || 10) : 10,
          bold: lics ? (lics.fontWeight === '700' || lics.fontWeight === 'bold') : false,
          columns,
        },
      };
    }

    saveBtn.addEventListener('click', async () => {
      // The \u escapes (not the literal glyphs) keep this file ASCII while
      // rendering the SAME text as the eight per-document designers, so an e2e
      // copied from one of them still matches.
      saveBtn.textContent = 'Saving\u2026';
      try {
        // When a named-layout picker exists (currently PO only -- see the
        // layoutPicker banner comment above), Save targets whatever it is
        // CURRENTLY EDITING, not silently the scope's default. `layoutPicker`
        // is declared further down this same function; referencing it here is
        // safe because this closure only runs on a later click, by which time
        // initPreprintedDesigner has already finished assigning it (null where
        // the template renders no #ppLayoutPicker, e.g. PR/RR).
        const body = collect();
        if (layoutPicker && layoutPicker.value) body.layout_id = layoutPicker.value;
        const resp = await fetch(saveUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify(body),
        });
        if (resp.ok) {
          if (!document.getElementById('layoutSavedFlag')) {
            const flag = document.createElement('span');
            flag.id = 'layoutSavedFlag';
            flag.style.display = 'none';
            document.body.appendChild(flag);
          }
          saveBtn.textContent = 'Saved \u2713';
          setTimeout(() => { saveBtn.textContent = 'Save Layout'; }, 1500);
        } else {
          saveBtn.textContent = 'Save failed';
          let reason = 'Save failed. Please try again.';
          try {
            const body = await resp.json();
            if (body && body.error) reason = body.error;
          } catch (parseErr) { /* non-JSON error body -- keep the generic reason */ }
          showNotice(reason);
        }
      } catch (err) {
        saveBtn.textContent = 'Save failed';
        showNotice('Save failed. Please try again.');
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
      el.style.left = clampFieldX(80) + 'px';
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

    // date format: live-preview the document's dates. Keys + strftime mirror
    // preprinted_base.DATE_FORMATS (day/month zero-padded, matching strftime).
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

    // --- Named layout picker: see the config.layoutPicker banner comment above.
    // A no-op wherever the template did not render #ppLayoutPicker or did not pass
    // layoutPicker config (PR, RR today). ---
    const layoutPicker = document.getElementById('ppLayoutPicker');
    if (layoutPicker && cfg.layoutPicker) {
      const lp = cfg.layoutPicker;
      const deviceSpan = document.getElementById('ppDeviceLayout');
      const saveAsBtn = document.getElementById('ppSaveAsBtn');
      const renameBtn = document.getElementById('ppRenameBtn');
      const deleteBtn = document.getElementById('ppDeleteLayoutBtn');
      const useHereBtn = document.getElementById('ppUseHereBtn');

      function selectedOption() { return layoutPicker.options[layoutPicker.selectedIndex] || null; }

      function withBranch(body) {
        if (lp.branchId !== undefined && lp.branchId !== null) body.branch_id = lp.branchId;
        return body;
      }

      async function postJSON(url, body) {
        let resp;
        try {
          resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify(body),
          });
        } catch (err) {
          showNotice('That did not work. Please try again.');
          return null;
        }
        let payload = null;
        try { payload = await resp.json(); } catch (parseErr) { payload = null; }
        if (!resp.ok || !payload || payload.ok === false) {
          showNotice((payload && payload.error) || 'That did not work. Please try again.');
          return null;
        }
        return payload;
      }

      function isOptionValue(sel, value) {
        return [...sel.options].some((o) => o.value === value);
      }

      // Reverse of collect(): repaint the canvas from a stored layout's JSON so the
      // picker can show what THIS layout looks like -- Decision 3, "changes what you
      // are EDITING". Never touches ppDeviceLayout and never calls the network.
      function applyLayoutToCanvas(data) {
        if (!data || typeof data !== 'object') return;
        if (paperSel && isOptionValue(paperSel, data.paper)) paperSel.value = data.paper;
        if (dateSel && isOptionValue(dateSel, data.dateFormat)) dateSel.value = data.dateFormat;
        if (fontSel && data.page && isOptionValue(fontSel, data.page.fontFamily)) {
          fontSel.value = data.page.fontFamily;
          document.body.style.fontFamily = fontSel.value;
        }
        if (paperSel) {
          const opt = paperSel.selectedOptions[0];
          const ps = document.getElementById('ppPageStyle');
          if (opt) {
            document.body.dataset.paper = paperSel.value;
            canvas.style.width = opt.dataset.w + 'px';
            canvas.style.height = opt.dataset.h + 'px';
            if (ps) ps.textContent = '@page { size: ' + opt.dataset.css + '; margin: 0; }';
          }
        }
        if (dateSel) dateSel.dispatchEvent(new Event('change'));

        Object.keys(data.fields || {}).forEach((key) => {
          const el = canvas.querySelector('.pp-el[data-el="' + key + '"]:not([data-extra])');
          if (!el) return;
          const f = data.fields[key];
          el.style.left = f.x + 'px';
          el.style.top = f.y + 'px';
          if (f.w !== undefined) el.style.width = f.w + 'px';
          el.style.fontSize = f.fontSize + 'px';
          el.style.fontWeight = f.bold ? 'bold' : 'normal';
          el.classList.toggle('pp-field-hidden', !!f.hidden);
          const cb = fieldStrip && fieldStrip.querySelector('[data-fieldtoggle="' + key + '"]');
          if (cb) cb.checked = !f.hidden;
        });

        // Extras/texts vary in count per saved layout -- replace wholesale rather
        // than trying to reconcile in place.
        canvas.querySelectorAll('.pp-el[data-extra]').forEach((el) => el.remove());
        (data.extras || []).forEach((ex) => {
          const base = canvas.querySelector('.pp-el[data-el="' + ex.key + '"]:not([data-extra])');
          const el = document.createElement('div');
          el.className = 'pp-el';
          el.dataset.el = ex.key;
          el.dataset.extra = '1';
          el.dataset.label = (base && base.dataset.label) || ex.key;
          el.textContent = base ? base.textContent : '';
          el.style.left = ex.x + 'px';
          el.style.top = ex.y + 'px';
          el.style.fontSize = ex.fontSize + 'px';
          el.style.fontWeight = ex.bold ? 'bold' : 'normal';
          canvas.appendChild(el);
        });

        canvas.querySelectorAll('.pp-text').forEach((el) => el.remove());
        (data.texts || []).forEach((t) => {
          const el = document.createElement('div');
          el.className = 'pp-el pp-text' + (t.hidden ? ' pp-field-hidden' : '');
          el.dataset.text = t.id;
          el.dataset.label = t.text;
          el.textContent = t.text;
          el.style.left = t.x + 'px';
          el.style.top = t.y + 'px';
          el.style.fontSize = t.fontSize + 'px';
          el.style.fontWeight = t.bold ? 'bold' : 'normal';
          canvas.appendChild(el);
        });

        const li = data.lineItems || {};
        (li.columns || []).forEach((c) => {
          const col = canvas.querySelector('.pp-col[data-col="' + c.key + '"]');
          if (!col) return;
          col.style.left = c.x + 'px';
          col.style.width = c.width + 'px';
          col.classList.toggle('pp-col-hidden', !c.visible);
          const cb = colStrip && colStrip.querySelector('[data-coltoggle="' + c.key + '"]');
          if (cb) cb.checked = !!c.visible;
        });
        if (li.y !== undefined) cols().forEach((c) => { c.style.top = li.y + 'px'; });

        selectEl(null);
      }

      // Picking a layout ONLY changes what is being edited -- see Decision 3 in the
      // banner comment. It must never POST anything and must never touch
      // ppDeviceLayout.
      layoutPicker.addEventListener('change', () => {
        const opt = selectedOption();
        if (!opt) return;
        let data = null;
        try { data = JSON.parse(opt.dataset.payload || '{}'); } catch (parseErr) { data = null; }
        applyLayoutToCanvas(data);
      });

      if (saveAsBtn && lp.saveAsUrl) {
        saveAsBtn.addEventListener('click', async () => {
          const raw = global.prompt(
            'Name it after the printer, not the person -- e.g. '
            + '"Purchasing - LX-310 Malandag". Layouts are shared, so one name per '
            + 'printer is enough.\n\nLayout name:');
          if (!raw || !raw.trim()) return;
          const name = raw.trim();
          const result = await postJSON(lp.saveAsUrl, withBranch(Object.assign({ name: name }, collect())));
          if (!result) return;
          const opt = document.createElement('option');
          opt.value = String(result.layout_id);
          opt.textContent = result.name;
          opt.dataset.payload = JSON.stringify(collect());
          layoutPicker.appendChild(opt);
          layoutPicker.value = opt.value;
          showNotice('Saved as "' + result.name + '".');
        });
      }

      if (renameBtn && lp.renameUrl) {
        renameBtn.addEventListener('click', async () => {
          const opt = selectedOption();
          if (!opt) return;
          const raw = global.prompt('Rename this layout:', opt.textContent);
          if (!raw || !raw.trim()) return;
          const name = raw.trim();
          const result = await postJSON(lp.renameUrl, { layout_id: opt.value, name: name });
          if (!result) return;
          const renamedDevice = deviceSpan && deviceSpan.dataset.layoutId === opt.value;
          opt.textContent = name;
          if (renamedDevice) deviceSpan.textContent = name;
        });
      }

      if (deleteBtn && lp.deleteUrl) {
        deleteBtn.addEventListener('click', async () => {
          const opt = selectedOption();
          if (!opt) return;
          if (!global.confirm('Delete layout "' + opt.textContent + '"?')) return;
          const result = await postJSON(lp.deleteUrl, { layout_id: opt.value });
          if (!result) return;
          const next = opt.nextElementSibling || opt.previousElementSibling;
          opt.remove();
          if (next) {
            layoutPicker.value = next.value;
            let data = null;
            try { data = JSON.parse(next.dataset.payload || '{}'); } catch (parseErr) { data = null; }
            applyLayoutToCanvas(data);
          }
        });
      }

      if (useHereBtn && lp.selectUrl) {
        useHereBtn.addEventListener('click', async () => {
          const opt = selectedOption();
          if (!opt) return;
          const result = await postJSON(lp.selectUrl, withBranch({ layout_id: opt.value }));
          if (!result) return;
          if (deviceSpan) {
            deviceSpan.textContent = opt.textContent;
            deviceSpan.dataset.layoutId = opt.value;
          }
          showNotice('This workstation now prints "' + opt.textContent + '".');
        });
      }
    }

    canvas.dataset.ppInit = '1';   // see the double-init guard at the top
    return true;
  }

  global.initPreprintedDesigner = initPreprintedDesigner;
})(window);
