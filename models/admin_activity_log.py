"""
AdminActivityLog model — tracks admin actions for auditing.
"""
import uuid
import datetime
from sqlalchemy import Column, String, Text, DateTime
from db import Base


class AdminActivityLog(Base):
    """Tracks all admin actions for audit trail."""
    __tablename__ = "admin_activity_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    admin_email = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)  # "promote", "demote", "delete_user", etc.
    target_user_email = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
