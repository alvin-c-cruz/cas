// Create-form attachment queue (held in the browser until Save).
// Lists the files chosen in #createAttachments, flags unsupported types, and
// lets the user drop one before submitting. Shared by the PR / PO / RR / CDV
// create forms (attachments/_create_queue.html). Lifted from the AP form.
(function () {
    var input = document.getElementById('createAttachments');
    if (!input) return;                      // edit mode: no create-attachments input
    var list = document.getElementById('attachmentQueue');
    var ALLOWED = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt'];

    function ext(name) {
        var i = name.lastIndexOf('.');
        return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
    }
    function humanSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1048576).toFixed(1) + ' MB';
    }
    function render() {
        list.innerHTML = '';
        Array.prototype.forEach.call(input.files, function (f, idx) {
            var bad = ALLOWED.indexOf(ext(f.name)) === -1;
            var li = document.createElement('li');
            li.style.cssText = 'display:flex; align-items:center; gap:8px; padding:4px 0;'
                + (bad ? 'color:var(--danger, #c0392b);' : '');
            var label = document.createElement('span');
            label.textContent = f.name + ' (' + humanSize(f.size) + ')'
                + (bad ? ' — unsupported type, will be skipped' : '');
            var rm = document.createElement('button');
            rm.type = 'button';
            rm.className = 'btn btn-secondary';
            rm.style.cssText = 'font-size:12px; padding:2px 8px;';
            rm.textContent = 'Remove';
            rm.addEventListener('click', function () { removeAt(idx); });
            li.appendChild(label);
            li.appendChild(rm);
            list.appendChild(li);
        });
    }
    function removeAt(idx) {
        var dt = new DataTransfer();
        Array.prototype.forEach.call(input.files, function (f, i) {
            if (i !== idx) dt.items.add(f);
        });
        input.files = dt.files;              // keep the real FileList in sync for submit
        render();
    }
    input.addEventListener('change', render);
})();
