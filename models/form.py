import uuid
import datetime
from sqlalchemy import Column, String, Integer, JSON, DateTime, Enum as SAEnum
from sqlalchemy.orm import relationship
from db import Base


class Form(Base):
    __tablename__ = "forms"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_by = Column(String, nullable=False, index=True)  # user email
    title = Column(String, nullable=False)
    description = Column(String, default="")
    status = Column(
        SAEnum("draft", "published", "closed", name="form_status", create_constraint=True),
        default="draft",
    )
    response_count = Column(Integer, default=0)
    questions = Column(JSON, default=list)
    branding = Column(JSON, default=dict)
    quiz = Column(JSON, default=dict)
    presentation = Column(JSON, default=dict)
    created_date = Column(DateTime, default=datetime.datetime.utcnow)
    updated_date = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    # Relationships
    responses = relationship("FormResponse", back_populates="form", cascade="all, delete-orphan")
    shares = relationship("FormShare", back_populates="form", cascade="all, delete-orphan")
    sections = relationship("FormSection", back_populates="form", order_by="FormSection.order", cascade="all, delete-orphan")
