/* Pre-printed voucher form designer (P-69 Task 5).
 *
 * Vanilla JS -- no build step, no JS popups (no confirm/alert/prompt).
 * Reads window.__PREPRINTED_DESIGNER__ (set inline by designer.html) for the
 * initial state, then lets the user:
 *   - click a palette field to place a chip on the canvas (default position)
 *   - drag a chip to reposition it (position captured in mm via the px<->mm
 *     scale, snapped to 0.5mm)
 *   - right-click a chip to toggle its `visible` flag (dimmed style when
 *     hidden)
 *   - remove a chip via its per-chip remove control
 *   - configure the line-band columns/anchor/row-height/max-rows
 * On Save, the current state is serialized into the two hidden JSON inputs
 * that the `save` route reads (`fields_json`, `line_band_json`).
 */
(function () {
    'use strict';

    var data = window.__PREPRINTED_DESIGNER__;
    if (!data) {
        return;
    }

    var canvas = document.getElementById('designer-canvas');
    var scale = data.scale || 3;
    var fields = (data.fields || []).slice();

    var paletteButtons = Array.prototype.slice.call(
        document.querySelectorAll('.designer-palette-btn')
    );

    var saveForm = document.getElementById('designer-save-form');
    var fieldsJsonInput = document.getElementById('designer-fields-json');
    var lineBandJsonInput = document.getElementById('designer-line-band-json');

    function snap(mm) {
        return Math.round(mm * 2) / 2;
    }

    function labelFor(key) {
        for (var i = 0; i < (data.headerFields || []).length; i++) {
            if (data.headerFields[i].key === key) {
                return data.headerFields[i].label;
            }
        }
        return key;
    }

    function updatePaletteState() {
        paletteButtons.forEach(function (btn) {
            var placed = fields.some(function (f) {
                return f.key === btn.dataset.key;
            });
            btn.classList.toggle('is-placed', placed);
        });
    }

    function removeField(key) {
        fields = fields.filter(function (f) {
            return f.key !== key;
        });
        renderCanvas();
    }

    function startDrag(field, chip, downEvent) {
        var canvasRect = canvas.getBoundingClientRect();
        var startX = downEvent.clientX;
        var startY = downEvent.clientY;
        var originLeft = parseFloat(chip.style.left) || 0;
        var originTop = parseFloat(chip.style.top) || 0;

        function onMove(moveEvent) {
            var dx = moveEvent.clientX - startX;
            var dy = moveEvent.clientY - startY;
            var newLeft = originLeft + dx;
            var newTop = originTop + dy;
            newLeft = Math.max(0, Math.min(newLeft, canvasRect.width - chip.offsetWidth));
            newTop = Math.max(0, Math.min(newTop, canvasRect.height - chip.offsetHeight));
            chip.style.left = newLeft + 'px';
            chip.style.top = newTop + 'px';
        }

        function onUp() {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            var left = parseFloat(chip.style.left) || 0;
            var top = parseFloat(chip.style.top) || 0;
            var xMm = snap(left / scale);
            var yMm = snap(top / scale);
            field.x_mm = xMm;
            field.y_mm = yMm;
            chip.style.left = (xMm * scale) + 'px';
            chip.style.top = (yMm * scale) + 'px';
        }

        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }

    function createChipElement(field) {
        var chip = document.createElement('div');
        chip.className = 'designer-chip' + (field.visible === false ? ' is-hidden' : '');
        chip.dataset.key = field.key;
        chip.style.left = ((field.x_mm || 0) * scale) + 'px';
        chip.style.top = ((field.y_mm || 0) * scale) + 'px';

        var label = document.createElement('span');
        label.className = 'designer-chip-label';
        label.textContent = labelFor(field.key);
        chip.appendChild(label);

        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'designer-chip-remove';
        removeBtn.textContent = '×';
        removeBtn.setAttribute('aria-label', 'Remove ' + labelFor(field.key));
        chip.appendChild(removeBtn);

        removeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            removeField(field.key);
        });

        chip.addEventListener('mousedown', function (e) {
            if (e.button !== 0) {
                return;
            }
            e.preventDefault();
            startDrag(field, chip, e);
        });

        chip.addEventListener('contextmenu', function (e) {
            e.preventDefault();
            field.visible = field.visible === false ? true : false;
            chip.classList.toggle('is-hidden', field.visible === false);
        });

        return chip;
    }

    function renderCanvas() {
        if (!canvas) {
            return;
        }
        var existingChips = canvas.querySelectorAll('.designer-chip');
        existingChips.forEach(function (chip) {
            chip.remove();
        });
        fields.forEach(function (field) {
            canvas.appendChild(createChipElement(field));
        });
        updatePaletteState();
    }

    paletteButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            var key = btn.dataset.key;
            var alreadyPlaced = fields.some(function (f) {
                return f.key === key;
            });
            if (alreadyPlaced) {
                return;
            }
            fields.push({
                key: key,
                x_mm: 10,
                y_mm: 10,
                font_size: 10,
                align: 'L',
                visible: true,
                width_mm: 40
            });
            renderCanvas();
        });
    });

    // --- Line band -----------------------------------------------------

    var lineBand = data.lineBand || {};
    var lbAnchorY = document.getElementById('lb-anchor-y');
    var lbRowHeight = document.getElementById('lb-row-height');
    var lbMaxRows = document.getElementById('lb-max-rows');
    var lbFontSize = document.getElementById('lb-font-size');

    (lineBand.columns || []).forEach(function (col) {
        var row = document.querySelector('#lb-columns-table tr[data-key="' + col.key + '"]');
        if (!row) {
            return;
        }
        var includeBox = row.querySelector('.lb-col-include');
        var xInput = row.querySelector('.lb-col-x');
        var widthInput = row.querySelector('.lb-col-width');
        var alignSelect = row.querySelector('.lb-col-align');
        if (includeBox) {
            includeBox.checked = true;
        }
        if (xInput) {
            xInput.value = col.x_mm != null ? col.x_mm : 0;
        }
        if (widthInput) {
            widthInput.value = col.width_mm != null ? col.width_mm : 40;
        }
        if (alignSelect) {
            alignSelect.value = col.align || 'L';
        }
    });

    // --- Save ------------------------------------------------------------

    if (saveForm) {
        saveForm.addEventListener('submit', function () {
            if (fieldsJsonInput) {
                fieldsJsonInput.value = JSON.stringify(fields);
            }

            var columns = [];
            document.querySelectorAll('#lb-columns-table tr[data-key]').forEach(function (row) {
                var includeBox = row.querySelector('.lb-col-include');
                if (!includeBox || !includeBox.checked) {
                    return;
                }
                columns.push({
                    key: row.dataset.key,
                    x_mm: parseFloat(row.querySelector('.lb-col-x').value) || 0,
                    width_mm: parseFloat(row.querySelector('.lb-col-width').value) || 40,
                    align: row.querySelector('.lb-col-align').value
                });
            });

            var serializedLineBand = {
                anchor_y_mm: parseFloat(lbAnchorY && lbAnchorY.value) || 0,
                row_height_mm: parseFloat(lbRowHeight && lbRowHeight.value) || 0,
                max_rows: parseInt(lbMaxRows && lbMaxRows.value, 10) || 0,
                font_size: parseFloat(lbFontSize && lbFontSize.value) || 9,
                columns: columns
            };
            if (lineBandJsonInput) {
                lineBandJsonInput.value = JSON.stringify(serializedLineBand);
            }
        });
    }

    renderCanvas();
})();
