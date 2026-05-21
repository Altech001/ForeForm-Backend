import uuid
import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from db import Base


class FormShare(Base):
    __tablename__ = "form_shares"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    form_id = Column(String, ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True)
    shared_with_email = Column(String, nullable=False, index=True)
    permission = Column(
        SAEnum("editor", "viewer", name="share_permission", create_constraint=True),
        default="viewer",
    )
    shared_by = Column(String, nullable=False)  # email of the admin who shared
    created_date = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    form = relationship("Form", back_populates="shares")
