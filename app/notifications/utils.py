"""
Notification utility functions
"""
from app import db
from app.notifications.models import Notification


def create_notification(user_id, title, message, category='info', related_type=None, related_id=None):
    """
    Create a notification for a user

    Args:
        user_id: ID of the user to notify
        title: Notification title
        message: Notification message
        category: 'success', 'info', 'warning', 'error'
        related_type: Optional type of related object
        related_id: Optional ID of related object

    Returns:
        Notification object if successful, None if error
    """
    try:
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            category=category,
            related_type=related_type,
            related_id=related_id
        )
        db.session.add(notification)
        db.session.commit()
        return notification
    except Exception as e:
        print(f"Error creating notification: {str(e)}")
        db.session.rollback()
        return None


def mark_as_read(notification_id):
    """Mark a notification as read"""
    from app.utils import ph_now
    try:
        notification = Notification.query.get(notification_id)
        if notification:
            notification.is_read = True
            notification.read_at = ph_now()
            db.session.commit()
            return True
        return False
    except Exception as e:
        print(f"Error marking notification as read: {str(e)}")
        db.session.rollback()
        return False


def get_unread_count(user_id):
    """Get count of unread notifications for a user"""
    try:
        return Notification.query.filter_by(user_id=user_id, is_read=False).count()
    except:
        return 0
