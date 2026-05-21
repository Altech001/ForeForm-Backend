import uuid
from sqlalchemy import Column, String, Integer, JSON, ForeignKey
from sqlalchemy.orm import relationship
from db import Base


class FormSection(Base):
    __tablename__ = "form_sections"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    form_id = Column(String, ForeignKey("forms.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    order = Column(Integer, default=0)
    
    # Store questions list for this section specifically
    # Each question follows the Question schema (id, type, label, required, options, condition)
    questions = Column(JSON, default=list)

    # Relationship back to the form
    form = relationship("Form", back_populates="sections")
