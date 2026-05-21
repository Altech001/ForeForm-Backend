
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


# ── Nested objects ───────────────────────────────────────────

class AnswerItem(BaseModel):
    question_id: str
    question_label: Optional[str] = None
    question_type: Optional[str] = None
    answer: Optional[str] = None
    is_correct: Optional[bool] = None
    points_earned: Optional[float] = None
    points_possible: Optional[float] = None


# ── Create ───────────────────────────────────────────────────

class ResponseCreate(BaseModel):
    respondent_name: Optional[str] = None
    respondent_email: Optional[str] = None
    signature_data_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    gps_accuracy: Optional[float] = None
    gps_address: Optional[str] = None
    answers: List[AnswerItem] = []
    quiz_score: Optional[float] = None
    quiz_max_score: Optional[float] = None
    quiz_percent: Optional[float] = None
    grades_released: Optional[bool] = False


# ── Read / Response ──────────────────────────────────────────

class ResponseOut(BaseModel):
    id: str
    form_id: str
    respondent_name: Optional[str] = None
    respondent_email: Optional[str] = None
    signature_data_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    gps_accuracy: Optional[float] = None
    gps_address: Optional[str] = None
    answers: Any  # JSON
    quiz_score: Optional[float] = None
    quiz_max_score: Optional[float] = None
    quiz_percent: Optional[float] = None
    grades_released: bool = False
    created_date: datetime
    updated_date: Optional[datetime] = None

    class Config:
        from_attributes = True
