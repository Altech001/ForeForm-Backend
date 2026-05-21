from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from typing import Optional, List
from datetime import datetime

class TaskActivityBase(BaseModel):
    action: str
    user: str

class TaskActivityCreate(TaskActivityBase):
    pass

class TaskActivityOut(TaskActivityBase):
    id: str
    created_at: datetime
    task_id: str

    model_config = ConfigDict(from_attributes=True)


class TaskAssigneeOut(BaseModel):
    id: str
    email: str
    assigned_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: Optional[str] = "todo"
    priority: Optional[str] = "medium"
    due_date: Optional[datetime] = None
    assignee_email: Optional[str] = None  # DEPRECATED: kept for backward compat
    attachment_url: Optional[str] = None

class TaskCreate(TaskBase):
    assignee_emails: Optional[List[str]] = None  # New: list of emails to assign

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    assignee_email: Optional[str] = None  # DEPRECATED
    assignee_emails: Optional[List[str]] = None  # New: replace assignees with this list
    attachment_url: Optional[str] = None

class TaskOut(TaskBase):
    id: str
    user_id: str
    created_at: datetime
    activities: List[TaskActivityOut] = []
    assignees: List[TaskAssigneeOut] = []
    assignee_emails: List[str] = []  # Convenience flat list of emails

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def populate_assignee_emails(self):
        """Populate the flat assignee_emails list from the ORM relationship."""
        if self.assignees and not self.assignee_emails:
            self.assignee_emails = [a.email for a in self.assignees]
        return self
