#type: ignore

from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime


_session_config = ConfigDict(protected_namespaces=(), from_attributes=True)


# ── Agent Session Schemas ────────────────────────────────────

class AgentSessionCreate(BaseModel):
    model_config = _session_config
    title: Optional[str] = "Untitled Chat"
    messages: List[Any] = []
    artifacts: List[Any] = []
    model_used: Optional[str] = "gemini-flash-latest"
    metadata: Optional[dict] = {}


class AgentSessionUpdate(BaseModel):
    model_config = _session_config
    title: Optional[str] = None
    messages: Optional[List[Any]] = None
    artifacts: Optional[List[Any]] = None
    model_used: Optional[str] = None
    metadata: Optional[dict] = None
    is_pinned: Optional[bool] = None


class AgentSessionOut(BaseModel):
    model_config = _session_config
    id: str
    user_id: str
    title: str
    messages: List[Any]
    artifacts: List[Any]
    model_used: Optional[str]
    metadata: Optional[dict]
    is_pinned: bool
    created_at: datetime
    updated_at: datetime




class AgentSessionSummary(BaseModel):
    model_config = _session_config
    """Lightweight summary for session list — no full messages."""
    id: str
    title: str
    model_used: Optional[str]
    is_pinned: bool
    message_count: int = 0
    created_at: datetime
    updated_at: datetime




# ── API Key Schemas ──────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    provider: str = "gemini"
    label: Optional[str] = "Default Key"
    api_key: str
    is_shared: bool = True
    is_default: bool = False


class ApiKeyUpdate(BaseModel):
    label: Optional[str] = None
    api_key: Optional[str] = None
    is_shared: Optional[bool] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class ApiKeyOut(BaseModel):
    id: str
    user_id: str
    provider: str
    label: Optional[str]
    api_key_masked: str  # Only show last 4 chars
    is_shared: bool
    is_active: bool
    is_default: bool
    usage_count: str
    last_used_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ApiKeyFull(BaseModel):
    """Full key value — only for the owner or during resolve."""
    id: str
    provider: str
    api_key: str
    is_shared: bool
    is_active: bool

    class Config:
        from_attributes = True


class ModelSwitch(BaseModel):
    model_id: str