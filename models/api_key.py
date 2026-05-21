import uuid
import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text
from db import Base


class ApiKey(Base):
    """Stores user-provided API keys. Keys can be shared org-wide by default."""
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String, nullable=False, default="gemini")  # gemini, openai, anthropic, etc.
    label = Column(String, nullable=True, default="Default Key")  # user-friendly name
    api_key = Column(Text, nullable=False)  # encrypted/stored key value
    is_shared = Column(Boolean, default=True)  # shared with all users by default
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)  # default key for the provider
    usage_count = Column(String, default="0")  # track usage
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
