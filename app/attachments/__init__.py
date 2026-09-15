"""Shared document attachments (PR, PO, RR, CDV).

See docs/design/2026-09-15-document-attachments-design.md.
"""
from flask import Blueprint

attachments_bp = Blueprint('attachments', __name__, template_folder='templates')

from app.attachments import views  # noqa: E402,F401  (registers routes + Jinja global)
