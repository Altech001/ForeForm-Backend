import uuid
import datetime
from sqlalchemy import Column, String, DateTime, Text, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from db import Base


class AgentSession(Base):
    """Stores AI agent chat sessions per user — like vector staff data."""
    __tablename__ = "agent_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False, default="Untitled Chat")
    messages = Column(JSON, nullable=False, default=list)  # Full chat history
    artifacts = Column(JSON, nullable=True, default=list)  # Generated artifacts (questions, sections, etc.)
    model_used = Column(String, nullable=True, default="gemini-flash-latest")
    metadata_ = Column("metadata", JSON, nullable=True, default=dict)  # Extra config/context
    is_pinned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
