"""
FormResponse model — stores individual form submissions.
"""
import uuid
import datetime
from sqlalchemy import Column, String, Float, Boolean, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from db import Base


class FormResponse(Base):
    __tablename__ = "form_responses"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    form_id = Column(String, ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True)
    respondent_name = Column(String)
    respondent_email = Column(String)
    signature_data_url = Column(String)       # base64 PNG data URL
    gps_latitude = Column(Float)
    gps_longitude = Column(Float)
    gps_accuracy = Column(Float)              # meters
    gps_address = Column(String)
    answers = Column(JSON, default=list)
    quiz_score = Column(Float)
    quiz_max_score = Column(Float)
    quiz_percent = Column(Float)
    grades_released = Column(Boolean, default=False)
    created_date = Column(DateTime, default=datetime.datetime.utcnow)
    updated_date = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    form = relationship("Form", back_populates="responses")
