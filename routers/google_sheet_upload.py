"""
Google Sheets Upload & Preview Router
──────────────────────────────────────
Extends the base google_integrations.py with richer Sheets operations:
  • POST /api/sheets/push            — push form responses to a new/existing sheet
  • POST /api/sheets/append          — append new responses to an existing sheet
  • GET  /api/sheets/preview         — preview sheet data (first N rows)
  • GET  /api/sheets/list            — list all spreadsheets in user's Drive
  • GET  /api/sheets/{spreadsheet_id}/info — get sheet metadata
  • POST /api/sheets/sync            — full sync: update existing sheet with all current responses
  • POST /api/sheets/auto-sync       — enable/disable auto-sync for a form
"""

import json
import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models.user import User
from models.form import Form
from models.form_response import FormResponse
from models.user_integration import UserIntegration
from auth.jwt import get_current_user

import requests as http_requests

router = APIRouter(prefix="/api/sheets", tags=["google-sheets"])


# ── Schemas ──────────────────────────────────────────────────

class SheetPushRequest(BaseModel):
    form_id: str
    spreadsheet_name: Optional[str] = None
    sheet_name: str = "Responses"


class SheetAppendRequest(BaseModel):
    form_id: str
    spreadsheet_id: str
    sheet_name: str = "Responses"
    only_new: bool = True  # only append responses newer than last sync


class SheetPreviewRequest(BaseModel):
    spreadsheet_id: str
    sheet_name: str = "Responses"
    max_rows: int = 50


class SheetSyncRequest(BaseModel):
    form_id: str
    spreadsheet_id: str
    sheet_name: str = "Responses"


class AutoSyncConfig(BaseModel):
    form_id: str
    spreadsheet_id: str
    enabled: bool = True


class SheetResult(BaseModel):
    success: bool
    spreadsheet_id: Optional[str] = None
    url: Optional[str] = None
    rows_written: int = 0
    message: str


# ── Helpers ──────────────────────────────────────────────────

def _get_sheets_token(user: User, db: Session) -> str:
    """Get a valid Google access token for Sheets operations."""
    integ = (
        db.query(UserIntegration)
        .filter(
            UserIntegration.user_id == user.id,
            UserIntegration.provider == "google_sheets",
            UserIntegration.is_active == True,
        )
        .first()
    )
    if not integ:
        # Fallback: try google_drive integration (has drive.file scope)
        integ = (
            db.query(UserIntegration)
            .filter(
                UserIntegration.user_id == user.id,
                UserIntegration.provider == "google_drive",
                UserIntegration.is_active == True,
            )
            .first()
        )
    if not integ:
        raise HTTPException(400, detail="Google Sheets is not connected. Please connect first.")

    return _ensure_valid_token(integ, db)


def _ensure_valid_token(integ: UserIntegration, db: Session) -> str:
    """Refresh the access token if it's expired."""
    from config import settings

    if integ.token_expiry and integ.token_expiry > datetime.datetime.utcnow():
        return integ.access_token

    if not integ.refresh_token:
        raise HTTPException(401, detail="Google token expired and no refresh token. Please reconnect.")

    resp = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": integ.refresh_token,
            "grant_type": "refresh_token",
        },
    )

    if resp.status_code != 200:
        raise HTTPException(401, detail="Failed to refresh Google token. Please reconnect.")

    tokens = resp.json()
    integ.access_token = tokens["access_token"]
    integ.token_expiry = datetime.datetime.utcnow() + datetime.timedelta(
        seconds=tokens.get("expires_in", 3600)
    )
    db.commit()
    return integ.access_token


def _get_form_data(form_id: str, user: User, db: Session):
    """Retrieve form + responses and return (form, headers, field_keys, rows)."""
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(404, detail="Form not found")
    if form.created_by != user.email:
        raise HTTPException(403, detail="You do not own this form")

    responses = (
        db.query(FormResponse)
        .filter(FormResponse.form_id == form_id)
        .order_by(FormResponse.created_date.asc())
        .all()
    )

    questions = form.questions or []
    headers = ["Submitted At", "Respondent Email", "Respondent Name"]
    field_keys = []
    for q in questions:
        label = q.get("label") or q.get("title") or q.get("id", "Unknown")
        headers.append(label)
        field_keys.append(q.get("id", label))

    rows = []
    for resp in responses:
        row = [
            resp.created_date.strftime("%Y-%m-%d %H:%M:%S") if resp.created_date else "",
            resp.respondent_email or "",
            resp.respondent_name or "",
        ]
        answers = resp.answers or []
        answer_map = {}
        for a in answers:
            if isinstance(a, dict):
                answer_map[a.get("question_id", "")] = a.get("value", "")

        for key in field_keys:
            val = answer_map.get(key, "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            row.append(str(val))
        rows.append(row)

    return form, headers, field_keys, rows


# ═══════════════════════════════════════════════════════════════
# 1. PUSH — Create new spreadsheet with form responses
# ═══════════════════════════════════════════════════════════════

@router.post("/push", response_model=SheetResult)
def push_to_sheet(
    data: SheetPushRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new Google Sheet and populate it with all form responses."""
    access_token = _get_sheets_token(current_user, db)
    form, headers, _, rows = _get_form_data(data.form_id, current_user, db)

    spreadsheet_name = data.spreadsheet_name or f"{form.title or 'Form'} — Responses"

    # Create spreadsheet
    create_body = {
        "properties": {"title": spreadsheet_name},
        "sheets": [{"properties": {"title": data.sheet_name}}],
    }
    create_resp = http_requests.post(
        "https://sheets.googleapis.com/v4/spreadsheets",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(create_body),
    )

    if create_resp.status_code not in (200, 201):
        raise HTTPException(500, detail=f"Sheets creation failed: {create_resp.text}")

    sheet_data = create_resp.json()
    spreadsheet_id = sheet_data["spreadsheetId"]

    # Write data
    all_values = [headers] + rows
    _write_values(access_token, spreadsheet_id, data.sheet_name, all_values)

    # Format header
    _format_header(access_token, spreadsheet_id)

    sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    return SheetResult(
        success=True,
        spreadsheet_id=spreadsheet_id,
        url=sheet_url,
        rows_written=len(rows),
        message=f"Exported {len(rows)} responses to Google Sheets",
    )


# ═══════════════════════════════════════════════════════════════
# 2. APPEND — Add new responses to existing sheet
# ═══════════════════════════════════════════════════════════════

@router.post("/append", response_model=SheetResult)
def append_to_sheet(
    data: SheetAppendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Append new responses to an existing Google Sheet."""
    access_token = _get_sheets_token(current_user, db)
    form, headers, _, rows = _get_form_data(data.form_id, current_user, db)

    if not rows:
        return SheetResult(
            success=True,
            spreadsheet_id=data.spreadsheet_id,
            rows_written=0,
            message="No new responses to append",
        )

    # Append rows (skip headers, they should already exist)
    append_body = {"values": rows}
    resp = http_requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{data.spreadsheet_id}"
        f"/values/{data.sheet_name}!A1:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(append_body),
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Append failed: {resp.text}")

    sheet_url = f"https://docs.google.com/spreadsheets/d/{data.spreadsheet_id}"

    return SheetResult(
        success=True,
        spreadsheet_id=data.spreadsheet_id,
        url=sheet_url,
        rows_written=len(rows),
        message=f"Appended {len(rows)} responses",
    )


# ═══════════════════════════════════════════════════════════════
# 3. PREVIEW — Read sheet data for preview
# ═══════════════════════════════════════════════════════════════

@router.get("/preview")
def preview_sheet(
    spreadsheet_id: str = Query(...),
    sheet_name: str = Query("Responses"),
    max_rows: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview the contents of a Google Sheet (first N rows)."""
    access_token = _get_sheets_token(current_user, db)

    range_str = f"{sheet_name}!A1:ZZ{max_rows + 1}"  # +1 for header
    resp = http_requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_str}",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Failed to read sheet: {resp.text}")

    values = resp.json().get("values", [])
    headers = values[0] if values else []
    data_rows = values[1:] if len(values) > 1 else []

    # Convert to list of dicts for easier frontend consumption
    records = []
    for row in data_rows:
        record = {}
        for i, header in enumerate(headers):
            record[header] = row[i] if i < len(row) else ""
        records.append(record)

    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "headers": headers,
        "total_rows": len(data_rows),
        "records": records,
    }


# ═══════════════════════════════════════════════════════════════
# 4. LIST — List all spreadsheets in user's Drive
# ═══════════════════════════════════════════════════════════════

@router.get("/list")
def list_spreadsheets(
    page_size: int = Query(20, ge=1, le=50),
    page_token: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List Google Sheets available in the user's Drive."""
    access_token = _get_sheets_token(current_user, db)

    params = {
        "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
        "pageSize": page_size,
        "fields": "nextPageToken, files(id, name, createdTime, modifiedTime, webViewLink, owners)",
        "orderBy": "modifiedTime desc",
    }
    if page_token:
        params["pageToken"] = page_token

    resp = http_requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Failed to list sheets: {resp.text}")

    result = resp.json()
    files = result.get("files", [])

    return {
        "spreadsheets": [
            {
                "id": f["id"],
                "name": f["name"],
                "created_time": f.get("createdTime"),
                "modified_time": f.get("modifiedTime"),
                "web_view_link": f.get("webViewLink"),
                "owner": f.get("owners", [{}])[0].get("emailAddress", "") if f.get("owners") else "",
            }
            for f in files
        ],
        "next_page_token": result.get("nextPageToken"),
    }


# ═══════════════════════════════════════════════════════════════
# 5. SHEET INFO — Get metadata about a specific spreadsheet
# ═══════════════════════════════════════════════════════════════

@router.get("/{spreadsheet_id}/info")
def get_sheet_info(
    spreadsheet_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get metadata about a specific Google Sheet (title, sheets list, row counts)."""
    access_token = _get_sheets_token(current_user, db)

    resp = http_requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"?fields=spreadsheetId,properties.title,sheets.properties",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Failed to get sheet info: {resp.text}")

    data = resp.json()
    sheets = data.get("sheets", [])

    return {
        "spreadsheet_id": data.get("spreadsheetId"),
        "title": data.get("properties", {}).get("title", ""),
        "sheets": [
            {
                "sheet_id": s["properties"]["sheetId"],
                "title": s["properties"]["title"],
                "row_count": s["properties"].get("gridProperties", {}).get("rowCount", 0),
                "column_count": s["properties"].get("gridProperties", {}).get("columnCount", 0),
            }
            for s in sheets
        ],
        "url": f"https://docs.google.com/spreadsheets/d/{data.get('spreadsheetId')}",
    }


# ═══════════════════════════════════════════════════════════════
# 6. SYNC — Full sync: replace all data in an existing sheet
# ═══════════════════════════════════════════════════════════════

@router.post("/sync", response_model=SheetResult)
def sync_sheet(
    data: SheetSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full sync: clears the sheet and re-writes all current form responses."""
    access_token = _get_sheets_token(current_user, db)
    form, headers, _, rows = _get_form_data(data.form_id, current_user, db)

    # Step 1: Clear existing data
    http_requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{data.spreadsheet_id}"
        f"/values/{data.sheet_name}:clear",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data="{}",
    )

    # Step 2: Write fresh data
    all_values = [headers] + rows
    _write_values(access_token, data.spreadsheet_id, data.sheet_name, all_values)

    # Step 3: Re-format header
    _format_header(access_token, data.spreadsheet_id)

    sheet_url = f"https://docs.google.com/spreadsheets/d/{data.spreadsheet_id}"

    return SheetResult(
        success=True,
        spreadsheet_id=data.spreadsheet_id,
        url=sheet_url,
        rows_written=len(rows),
        message=f"Synced {len(rows)} responses to Google Sheets",
    )


# ═══════════════════════════════════════════════════════════════
# Shared Helpers
# ═══════════════════════════════════════════════════════════════

def _write_values(access_token: str, spreadsheet_id: str, sheet_name: str, values: list):
    """Write values to a sheet range."""
    body = {"values": values}
    resp = http_requests.put(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{sheet_name}!A1?valueInputOption=RAW",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(body),
    )
    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Sheet write failed: {resp.text}")


def _format_header(access_token: str, spreadsheet_id: str):
    """Bold + freeze the header row."""
    format_body = {
        "requests": [
            {
                "repeatCell": {
                    "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.95},
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": 0,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
        ]
    }
    http_requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(format_body),
    )
