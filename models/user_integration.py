import uuid
import datetime
from sqlalchemy import Column, String, DateTime, Text, Boolean
from db import Base


class UserIntegration(Base):
    """Stores per-user OAuth tokens for third-party integrations (Google Drive, Sheets, etc.)."""
    __tablename__ = "user_integrations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False)              # "google_drive" | "google_sheets"
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime, nullable=True)
    scopes = Column(Text, nullable=True)                   # comma-separated scopes
    connected_email = Column(String, nullable=True)        # the Google account email
    is_active = Column(Boolean, default=True)
    created_date = Column(DateTime, default=datetime.datetime.utcnow)
    updated_date = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
