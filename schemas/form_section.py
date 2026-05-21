from pydantic import BaseModel
from typing import Optional, List, Any
from schemas.form import Question


class FormSectionBase(BaseModel):
    title: str
    description: Optional[str] = ""
    order: int = 0
    questions: List[Question] = []


class FormSectionCreate(FormSectionBase):
    pass


class FormSectionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    order: Optional[int] = None
    questions: Optional[List[Question]] = None


class FormSectionOut(FormSectionBase):
    id: str
    form_id: str

    class Config:
        from_attributes = True
