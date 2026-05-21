"""
Admin schemas — Pydantic models for the admin dashboard & user management.
"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Any
from datetime import datetime


# ── Dashboard Stats ──────────────────────────────────────────

class DashboardStats(BaseModel):
    total_users: int
    total_forms: int
    total_responses: int
    total_tasks: int
    active_integrations: int
    users_today: int
    responses_today: int
    forms_today: int


class UserGrowthPoint(BaseModel):
    date: str
    count: int


class DashboardDetail(BaseModel):
    stats: DashboardStats
    recent_users: List[Any] = []
    user_growth: List[UserGrowthPoint] = []


# ── User Management ─────────────────────────────────────────

class AdminUserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    created_date: datetime
    form_count: int = 0
    response_count: int = 0
    integration_count: int = 0

    class Config:
        from_attributes = True


class UserRoleUpdate(BaseModel):
    role: str  # "admin" | "user"


class UserStatusUpdate(BaseModel):
    is_active: bool


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[EmailStr] = None


# ── Activity Log ─────────────────────────────────────────────

class AdminActivityLog(BaseModel):
    id: str
    admin_email: str
    action: str
    target_user_email: Optional[str] = None
    details: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


# ── Bulk Actions ─────────────────────────────────────────────

class BulkRoleUpdate(BaseModel):
    user_ids: List[str]
    role: str


class BulkActionResult(BaseModel):
    success: bool
    updated_count: int
    message: str
