from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


# ── OAuth Flow ───────────────────────────────────────────────

class GoogleOAuthCallback(BaseModel):
    code: str
    provider: str  # "google_drive" | "google_sheets"
    redirect_uri: Optional[str] = None


class IntegrationStatus(BaseModel):
    provider: str
    is_connected: bool
    connected_email: Optional[str] = None
    connected_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Push Operations ──────────────────────────────────────────

class PushToDriveRequest(BaseModel):
    form_id: str
    file_name: Optional[str] = None
    folder_name: Optional[str] = "ForeForm Exports"


class PushToSheetsRequest(BaseModel):
    form_id: str
    spreadsheet_name: Optional[str] = None


class PushResult(BaseModel):
    success: bool
    url: Optional[str] = None
    message: str
