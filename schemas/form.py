#type:ignore

from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum


# ── Enums ────────────────────────────────────────────────────

class FormStatus(str, Enum):
    draft = "draft"
    published = "published"
    closed = "closed"


class QuestionType(str, Enum):
    short_text = "short_text"
    long_text = "long_text"
    multiple_choice = "multiple_choice"
    checkbox = "checkbox"
    dropdown = "dropdown"
    date = "date"
    number = "number"
    email = "email"
    file_upload = "file_upload"
    rating = "rating"
    link = "link"


class ConditionOperator(str, Enum):
    equals = "equals"
    not_equals = "not_equals"
    contains = "contains"
    not_empty = "not_empty"


class HeaderStyle(str, Enum):
    minimal = "minimal"
    cover_image = "cover_image"
    split = "split"
    banner_solid = "banner_solid"
    banner_gradient = "banner_gradient"


class LogoPosition(str, Enum):
    left = "left"
    center = "center"
    right = "right"


class ThemeToken(str, Enum):
    default = "default"
    violet = "violet"
    blue = "blue"
    emerald = "emerald"
    rose = "rose"
    amber = "amber"
    indigo = "indigo"
    slate = "slate"


class ReleaseGrades(str, Enum):
    immediately = "immediately"
    manual = "manual"


# ── Nested objects ───────────────────────────────────────────

class QuestionCondition(BaseModel):
    source_question_id: Optional[str] = None
    operator: Optional[ConditionOperator] = None
    value: Optional[str] = None


class Question(BaseModel):
    id: str
    type: QuestionType
    label: str
    required: bool = False
    options: List[str] = []
    points: Optional[float] = None
    correct_answer: Optional[str] = None
    condition: Optional[QuestionCondition] = None
    link_url: Optional[str] = None
    link_button_text: Optional[str] = None


class Branding(BaseModel):
    logo_url: Optional[str] = None
    organization: Optional[str] = None
    research_title: Optional[str] = None
    appendix_label: Optional[str] = None
    ethics_statement: Optional[str] = None
    consent_text: Optional[str] = None
    require_signature: bool = False
    collect_gps: bool = False
    theme: Optional[ThemeToken] = ThemeToken.default
    header_style: Optional[HeaderStyle] = HeaderStyle.minimal
    cover_image_url: Optional[str] = None
    logo_position: Optional[LogoPosition] = LogoPosition.left
    font: Optional[str] = "inter"
    schedule_date: Optional[str] = None
    schedule_start: Optional[str] = None
    schedule_end: Optional[str] = None


class QuizSettings(BaseModel):
    enabled: bool = False
    release_grades: ReleaseGrades = ReleaseGrades.immediately
    show_missed_questions: bool = True
    show_correct_answers: bool = False
    show_point_values: bool = True
    default_points: float = 10


class PresentationSettings(BaseModel):
    show_progress_bar: bool = True
    shuffle_questions: bool = False
    confirmation_message: str = "Your response has been recorded"
    show_submit_another: bool = False
    show_results_summary: bool = False
    disable_autosave: bool = False
    collect_participant_details: bool = False


# ── Create / Update ─────────────────────────────────────────

class FormCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    questions: List[Question] = []
    status: FormStatus = FormStatus.draft
    branding: Optional[Branding] = None
    quiz: Optional[QuizSettings] = None
    presentation: Optional[PresentationSettings] = None


class FormUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    questions: Optional[List[Question]] = None
    status: Optional[FormStatus] = None
    response_count: Optional[int] = None
    branding: Optional[Branding] = None
    quiz: Optional[QuizSettings] = None
    presentation: Optional[PresentationSettings] = None


# ── Read / Response ──────────────────────────────────────────

class FormOut(BaseModel):
    id: str
    created_by: str
    title: str
    description: Optional[str] = ""
    status: str
    response_count: int
    questions: Any  # JSON
    branding: Any   # JSON
    quiz: Any
    presentation: Any
    created_date: datetime
    updated_date: Optional[datetime] = None

    class Config:
        from_attributes = True
