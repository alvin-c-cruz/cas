/* uom-quick-add.js
   Call initUomQuickAdd() once per page when the units_of_measure module is active.
   Exposes openUomModal(lineId, onSuccess) globally.  */

function initUomQuickAdd() {
    const overlay   = document.getElementById('uomQuickAddOverlay');
    const form      = document.getElementById('uomQuickAddForm');
    const errorBox  = document.getElementById('uomQuickAddError');
    const submitBtn = document.getElementById('uomQuickAddSubmit');
    if (!overlay || !form) return;

    let _onSuccess = null;

    window.openUomModal = function (lineId, onSuccess) {
        _onSuccess = onSuccess;
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        form.reset();
        overlay.style.display = 'flex';
        document.getElementById('uqa_code').focus();
    };

    function closeModal() {
        overlay.style.display = 'none';
        _onSuccess = null;
    }

    document.getElementById('uomQuickAddClose').addEventListener('click', closeModal);
    document.getElementById('uomQuickAddCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) closeModal(); });

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        errorBox.style.display = 'none';
        submitBtn.disabled = true;
        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
        .then(r => r.json().then(body => ({ status: r.status, body })))
        .then(function ({ status, body }) {
            if (status === 200 && body.ok) {
                if (_onSuccess) _onSuccess(body.unit);
                closeModal();
            } else {
                const errs = body.errors || {};
                const first = Object.values(errs)[0] || 'Could not create unit. Please check the fields.';
                errorBox.textContent = first;
                errorBox.style.display = '';
            }
        })
        .catch(function () {
            errorBox.textContent = 'Network error — unit was not saved.';
            errorBox.style.display = '';
        })
        .finally(function () { submitBtn.disabled = false; });
    });
}
