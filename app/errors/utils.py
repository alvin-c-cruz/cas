"""
Error Logging Utility Functions
Helper functions for logging errors to database and files
"""
import traceback
from flask import request, current_app
from flask_login import current_user
from app import db
from app.errors.models import ErrorLog


def log_error_to_db(exception, severity='ERROR', module=None):
    """
    Log error to database for critical issues.

    Args:
        exception (Exception): The exception that occurred
        severity (str): ERROR or CRITICAL
        module (str): Module/endpoint name (auto-detected from request if not provided)

    Returns:
        ErrorLog: The created error log entry, or None if logging failed
    """
    try:
        # Get request context if available
        request_url = None
        request_method = None
        request_data = None
        ip_address = None
        user_agent = None
        user_id = None

        if request:
            request_url = request.url
            request_method = request.method
            # Sanitize request data (don't log passwords, etc.)
            if request.form:
                sanitized_data = {k: '***' if 'password' in k.lower() else v
                                 for k, v in request.form.to_dict().items()}
                request_data = str(sanitized_data)
            ip_address = request.remote_addr
            user_agent = request.headers.get('User-Agent')

        if current_user and current_user.is_authenticated:
            user_id = current_user.id

        # Auto-detect module from request endpoint
        if not module and request:
            module = request.endpoint

        # Create error log entry
        error_log = ErrorLog(
            severity=severity,
            module=module,
            error_type=type(exception).__name__,
            error_message=str(exception),
            stack_trace=traceback.format_exc(),
            user_id=user_id,
            request_url=request_url,
            request_method=request_method,
            request_data=request_data,
            ip_address=ip_address,
            user_agent=user_agent
        )

        db.session.add(error_log)
        db.session.commit()

        return error_log

    except Exception as e:
        # Don't fail if error logging fails - just log to console
        current_app.logger.error(f"Failed to log error to database: {str(e)}")
        try:
            db.session.rollback()
        except:
            pass
        return None


def log_exception(exception, severity='ERROR', module=None, extra_context=None):
    """
    Comprehensive error logging to both file and database.

    Args:
        exception (Exception): The exception to log
        severity (str): ERROR or CRITICAL
        module (str): Module name
        extra_context (dict): Additional context to log

    This function:
    1. Logs to application logger (file)
    2. Logs to database (for UI viewing)
    3. Includes full context (user, request, stack trace)
    """
    # Log to file
    current_app.logger.error(
        f"Exception in {module or 'unknown'}: {str(exception)}",
        exc_info=True,
        extra={'context': extra_context} if extra_context else {}
    )

    # Log to database for critical errors
    if severity in ['ERROR', 'CRITICAL']:
        log_error_to_db(exception, severity, module)


def get_error_summary():
    """
    Get summary statistics of errors in the system.

    Returns:
        dict: Error statistics
    """
    from sqlalchemy import func

    total_errors = ErrorLog.query.count()
    unresolved_errors = ErrorLog.query.filter_by(is_resolved=False).count()

    # Errors by severity
    by_severity = db.session.query(
        ErrorLog.severity,
        func.count(ErrorLog.id)
    ).group_by(ErrorLog.severity).all()

    # Errors by module (top 5)
    by_module = db.session.query(
        ErrorLog.module,
        func.count(ErrorLog.id)
    ).group_by(ErrorLog.module).order_by(
        func.count(ErrorLog.id).desc()
    ).limit(5).all()

    return {
        'total_errors': total_errors,
        'unresolved_errors': unresolved_errors,
        'by_severity': dict(by_severity),
        'top_modules': dict(by_module)
    }
