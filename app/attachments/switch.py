"""Whether CAS takes file attachments at all.

Owner, 23 Oct 2026: "we are not implementing the uploading of file attachment documents in our app.
the free server got full" (Philgen's free PythonAnywhere disk reached 507 of 512 MB). Off unless the
server's .env sets ATTACHMENT_UPLOADS=true (config.py). While off:

- no document takes a new file: the upload routes refuse, the create forms and panels show no file
  input, and the service-level savers refuse too;
- no attachment slot is required, so no document waits on a file, is flagged for one in Action Items,
  or keeps an "approved with required files missing" badge;
- files attached before stay listed, and can still be previewed, downloaded and deleted wherever the
  document's own status and role rules allow.

The company logo is not an attachment and is not affected. Spec, beside the checkout:
app-docs/superpowers/specs/2026-10-23-attachment-uploads-off-design.md.
"""
from flask import current_app, has_app_context

OFF_MESSAGE = 'Files are no longer uploaded to CAS.'
OFF_NOTE = 'Files are no longer uploaded to CAS. The files below were attached before.'


def uploads_enabled():
    """True only when the running app's config turns attachments on. False outside an app context;
    callers that must fall back to the code seed there (config_overrides) check has_app_context()."""
    return has_app_context() and bool(current_app.config.get('ATTACHMENT_UPLOADS'))
