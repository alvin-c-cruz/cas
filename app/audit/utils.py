"""
Audit Log Utility Functions
Helper functions for logging changes to the audit trail
"""
import json
from flask import request
from flask_login import current_user
from app import db
from app.audit.models import AuditLog


def log_audit(module, action, record_id, record_identifier=None, old_values=None, new_values=None, notes=None):
    """
    Create an audit log entry

    Args:
        module (str): Module name (e.g., 'customer', 'vendor', 'vat_category')
        action (str): Action performed ('create', 'update', 'delete')
        record_id (int): ID of the affected record
        record_identifier (str): Human-readable identifier (name, code, etc.)
        old_values (dict): Dictionary of old values (for update/delete)
        new_values (dict): Dictionary of new values (for create/update)
        notes (str): Optional notes about the change

    Returns:
        AuditLog: The created audit log entry
    """
    try:
        # Get request context
        ip_address = request.remote_addr if request else None
        user_agent = request.headers.get('User-Agent') if request else None

        # Create audit log entry
        audit_log = AuditLog(
            module=module,
            action=action,
            record_id=record_id,
            record_identifier=record_identifier,
            user_id=current_user.id if current_user.is_authenticated else None,
            old_values=json.dumps(old_values) if old_values else None,
            new_values=json.dumps(new_values) if new_values else None,
            ip_address=ip_address,
            user_agent=user_agent,
            notes=notes
        )

        db.session.add(audit_log)
        db.session.commit()

        return audit_log

    except Exception as e:
        # Log the error but don't fail the main operation
        print(f"Error creating audit log: {str(e)}")
        db.session.rollback()
        return None


def log_create(module, record_id, record_identifier, new_values, notes=None):
    """Shortcut for logging CREATE operations"""
    return log_audit(
        module=module,
        action='create',
        record_id=record_id,
        record_identifier=record_identifier,
        new_values=new_values,
        notes=notes
    )


def log_update(module, record_id, record_identifier, old_values, new_values, notes=None):
    """Shortcut for logging UPDATE operations"""
    return log_audit(
        module=module,
        action='update',
        record_id=record_id,
        record_identifier=record_identifier,
        old_values=old_values,
        new_values=new_values,
        notes=notes
    )


def log_delete(module, record_id, record_identifier, old_values, notes=None):
    """Shortcut for logging DELETE operations"""
    return log_audit(
        module=module,
        action='delete',
        record_id=record_id,
        record_identifier=record_identifier,
        old_values=old_values,
        notes=notes
    )


def get_changes(old_obj, new_data, fields):
    """
    Compare old object with new data and return changes

    Args:
        old_obj: SQLAlchemy model instance
        new_data: Dictionary of new values
        fields: List of field names to compare

    Returns:
        tuple: (old_values_dict, new_values_dict) containing only changed fields
    """
    old_values = {}
    new_values = {}

    for field in fields:
        old_val = getattr(old_obj, field, None)
        new_val = new_data.get(field)

        # Convert to comparable types
        if old_val != new_val:
            old_values[field] = str(old_val) if old_val is not None else None
            new_values[field] = str(new_val) if new_val is not None else None

    return old_values, new_values


def model_to_dict(obj, fields):
    """
    Convert SQLAlchemy model to dictionary

    Args:
        obj: SQLAlchemy model instance
        fields: List of field names to include

    Returns:
        dict: Dictionary of field values
    """
    result = {}
    for field in fields:
        val = getattr(obj, field, None)
        result[field] = str(val) if val is not None else None
    return result
