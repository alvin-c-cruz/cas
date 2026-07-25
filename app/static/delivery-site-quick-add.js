/* delivery-site-quick-add.js
   Call initDeliverySiteQuickAdd() once per page on the Sales Order form.
   Exposes openDeliverySiteModal(lineId, customerId, onSuccess) globally.

   Locked to the header's currently-selected customer -- refuses to open with no
   customer selected. POSTs to Task 4's create_delivery_site route (nested under
   /customers/<id>/delivery-sites/create), rewriting the id in the form's
   data-url-template to the current customer before each open.

   IMPORTANT: unlike product-quick-add.js/uom-quick-add.js (which gate success on
   `status === 200 && body.ok`), this branches on the JSON body's `ok` field ALONE --
   create_delivery_site's AJAX branch returns HTTP 422 (not 400) on validation
   failure, so status is not a reliable success signal here. See
   app/customers/views.py::create_delivery_site's docstring. */

function initDeliverySiteQuickAdd() {
    const overlay    = document.getElementById('deliverySiteQuickAddOverlay');
    const form       = document.getElementById('deliverySiteQuickAddForm');
    const errorBox   = document.getElementById('deliverySiteQuickAddError');
    const submitBtn  = document.getElementById('deliverySiteQuickAddSubmit');
    if (!overlay || !form) return;

    const urlTemplate = form.getAttribute('data-url-template'); // .../customers/0/delivery-sites/create
    let _onSuccess = null;

    window.openDeliverySiteModal = function (lineId, customerId, onSuccess) {
        if (!customerId) return; // refuse to open with no customer selected
        _onSuccess = onSuccess;
        form.setAttribute('action', urlTemplate.replace(/\/customers\/\d+\//, '/customers/' + customerId + '/'));
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        form.reset();
        overlay.style.display = 'flex';
        document.getElementById('dsqa_name').focus();
    };

    function closeModal() {
        overlay.style.display = 'none';
        _onSuccess = null;
    }

    document.getElementById('deliverySiteQuickAddClose').addEventListener('click', closeModal);
    document.getElementById('deliverySiteQuickAddCancel').addEventListener('click', closeModal);
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
        .then(function ({ body }) {
            if (body.ok) {
                if (_onSuccess) _onSuccess(body.site);
                closeModal();
            } else {
                const errs = body.errors || {};
                const first = Object.values(errs)[0] || 'Could not create delivery site. Please check the name.';
                errorBox.textContent = first;
                errorBox.style.display = '';
            }
        })
        .catch(function () {
            errorBox.textContent = 'Network error — delivery site was not saved.';
            errorBox.style.display = '';
        })
        .finally(function () { submitBtn.disabled = false; });
    });
}
