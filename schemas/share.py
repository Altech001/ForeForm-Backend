from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from enum import Enum


class SharePermission(str, Enum):
    editor = "editor"
    viewer = "viewer"


class ShareCreate(BaseModel):
    shared_with_email: EmailStr
    permission: SharePermission = SharePermission.viewer


class ShareOut(BaseModel):
    id: str
    form_id: str
    shared_with_email: str
    permission: str
    shared_by: str
    created_date: datetime

    class Config:
        from_attributes = True
