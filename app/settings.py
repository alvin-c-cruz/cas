"""
Application settings module for storing system-wide configurations
"""
from app import db
from app.utils import ph_now


class AppSettings(db.Model):
    """Application settings model for system-wide configurations."""
    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    value = db.Column(db.String(200), nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by = db.Column(db.String(80))  # Username who updated

    def __repr__(self):
        return f'<AppSettings {self.key}={self.value}>'

    @staticmethod
    def get_setting(key, default=None):
        """Get a setting value by key."""
        setting = AppSettings.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set_setting(key, value, updated_by=None):
        """Set or update a setting value."""
        setting = AppSettings.query.filter_by(key=key).first()
        if setting:
            setting.value = value
            setting.updated_by = updated_by
            setting.updated_at = ph_now()
        else:
            setting = AppSettings(key=key, value=value, updated_by=updated_by)
            db.session.add(setting)
        db.session.commit()
        return setting
