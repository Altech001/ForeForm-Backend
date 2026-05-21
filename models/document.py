import uuid
import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import relationship
from db import Base

class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    type = Column(String, nullable=True)
    size = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_joint = Column(Boolean, default=False)
    
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    user = relationship("User")
