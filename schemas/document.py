from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class DocumentBase(BaseModel):
    name: str
    original_name: str
    url: str
    type: Optional[str] = None
    size: Optional[int] = 0
    is_joint: Optional[bool] = False

class DocumentCreate(DocumentBase):
    pass

class DocumentUpdate(BaseModel):
    name: Optional[str] = None
    is_joint: Optional[bool] = None

class DocumentOut(DocumentBase):
    id: str
    user_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
