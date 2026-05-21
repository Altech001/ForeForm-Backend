import uuid
import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SAEnum, Table
from sqlalchemy.orm import relationship
from db import Base

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, default="todo") # todo, in_progress, done
    priority = Column(String, default="medium") # high, medium, low
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    assignee_email = Column(String, nullable=True)  # DEPRECATED: kept for backward compat
    attachment_url = Column(String, nullable=True)
    
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    user = relationship("User")

    # Many-to-many: a task can have multiple assignees
    assignees = relationship("TaskAssignee", back_populates="task", cascade="all, delete-orphan")
    
    activities = relationship("TaskActivity", back_populates="task", cascade="all, delete-orphan", order_by="TaskActivity.created_at.desc()")

class TaskActivity(Base):
    __tablename__ = "task_activities"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    action = Column(String, nullable=False)
    user = Column(String, nullable=False) # e.g. "You" or email depending on ui
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    task = relationship("Task", back_populates="activities")


class TaskAssignee(Base):
    __tablename__ = "task_assignees"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    email = Column(String, nullable=False)
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)

    task = relationship("Task", back_populates="assignees")
