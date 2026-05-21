import uuid
import datetime
from sqlalchemy import Column, String, DateTime, Enum as SAEnum
from db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_date = Column(DateTime, default=datetime.datetime.utcnow)
    email = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(
        SAEnum("admin", "user", name="user_role", create_constraint=True),
        default="user",
    )
