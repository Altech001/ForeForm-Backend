"""
Google Drive & Google Sheets integration router.
──────────────────────────────────────────────────
Flow:
1. Frontend calls GET /api/integrations/google/auth-url?provider=google_drive
   → returns the Google OAuth2 consent URL
2. User is redirected to Google, grants permission, and Google redirects back
   to the frontend callback route with ?code=…
3. Frontend calls POST /api/integrations/google/callback with { code, provider }
   → backend exchanges the code for tokens, stores them in UserIntegration
4. Frontend can then POST /api/integrations/google/push-drive or push-sheets
   to export form data.
"""

import json
import datetime
from typing import List
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db import get_db
from config import settings
from models.user import User
from models.user_integration import UserIntegration
from models.form import Form
from models.form_response import FormResponse
from auth.jwt import get_current_user
from schemas.integration import (
    GoogleOAuthCallback,
    IntegrationStatus,
    PushToDriveRequest,
    PushToSheetsRequest,
    PushResult,
)

import requests as http_requests

router = APIRouter(prefix="/api/integrations/google", tags=["google-integrations"])

# ── Google OAuth2 constants ──────────────────────────────────

GOOGLE_CLIENT_ID = settings.GOOGLE_OAUTH_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_REDIRECT_URI = settings.GOOGLE_OAUTH_REDIRECT_URI

GOOGLE_IDENTITY_SCOPES = "openid email profile"

SCOPES_MAP = {
    "google_drive": f"{GOOGLE_IDENTITY_SCOPES} https://www.googleapis.com/auth/drive.file",
    "google_sheets": f"{GOOGLE_IDENTITY_SCOPES} https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive.file",
    "gmail": f"{GOOGLE_IDENTITY_SCOPES} https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly",
    "youtube": f"{GOOGLE_IDENTITY_SCOPES} https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload",
}


# ── 1. Generate OAuth URL ───────────────────────────────────

@router.get("/auth-url")
def get_auth_url(
    provider: str = Query(..., description="google_drive, google_sheets, gmail, or youtube"),
    redirect_uri: str = Query(None, description="Frontend redirect URI"),
    current_user: User = Depends(get_current_user),
):
    """Return the Google OAuth2 consent URL for the given provider."""
    if provider not in SCOPES_MAP:
        raise HTTPException(400, detail=f"Unknown provider: {provider}")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, detail="Google OAuth is not configured on the server.")

    scopes = SCOPES_MAP[provider]
    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri or GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": provider,
    })
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return {"auth_url": url}


# ── 2. OAuth Callback ───────────────────────────────────────

@router.post("/callback", response_model=IntegrationStatus)
def oauth_callback(
    data: GoogleOAuthCallback,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exchange the authorization code for tokens and store them."""
    if data.provider not in SCOPES_MAP:
        raise HTTPException(400, detail=f"Unknown provider: {data.provider}")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, detail="Google OAuth is not configured on the server.")

    token_resp = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": data.code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": data.redirect_uri or GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )

    if token_resp.status_code != 200:
        detail = token_resp.json().get("error_description", "Token exchange failed")
        raise HTTPException(400, detail=detail)

    tokens = token_resp.json()
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)
    token_expiry = datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)

    # Get connected Google email
    userinfo = http_requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    ).json()
    connected_email = userinfo.get("email", "")

    # Upsert the integration record
    existing = (
        db.query(UserIntegration)
        .filter(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == data.provider,
        )
        .first()
    )

    if existing:
        existing.access_token = access_token
        existing.refresh_token = refresh_token or existing.refresh_token
        existing.token_expiry = token_expiry
        existing.scopes = SCOPES_MAP.get(data.provider, "")
        existing.connected_email = connected_email
        existing.is_active = True
        existing.updated_date = datetime.datetime.utcnow()
    else:
        integration = UserIntegration(
            user_id=current_user.id,
            provider=data.provider,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
            scopes=SCOPES_MAP.get(data.provider, ""),
            connected_email=connected_email,
            is_active=True,
        )
        db.add(integration)

    db.commit()

    return IntegrationStatus(
        provider=data.provider,
        is_connected=True,
        connected_email=connected_email,
        connected_at=datetime.datetime.utcnow(),
    )


# ── 3. Status ───────────────────────────────────────────────

@router.get("/status", response_model=List[IntegrationStatus])
def get_integration_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return connection status for all Google integrations."""
    integrations = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == current_user.id, UserIntegration.is_active == True)
        .all()
    )
    results = []
    for integ in integrations:
        results.append(
            IntegrationStatus(
                provider=integ.provider,
                is_connected=True,
                connected_email=integ.connected_email,
                connected_at=integ.created_date,
                scopes=integ.scopes,
            )
        )

    # Fill in not-connected providers
    connected_providers = {r.provider for r in results}
    for prov in SCOPES_MAP:
        if prov not in connected_providers:
            results.append(
                IntegrationStatus(
                    provider=prov,
                    is_connected=False,
                    scopes=SCOPES_MAP[prov],
                    setup_required=not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET,
                    message=(
                        "Google OAuth is not configured on the server."
                        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET
                        else None
                    ),
                )
            )

    return results


# ── 4. Disconnect ────────────────────────────────────────────

@router.delete("/disconnect")
def disconnect_integration(
    provider: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disconnect (soft-delete) a Google integration."""
    integ = (
        db.query(UserIntegration)
        .filter(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == provider,
        )
        .first()
    )
    if integ:
        # Optionally revoke the token at Google
        try:
            http_requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": integ.access_token},
            )
        except Exception:
            pass
        db.delete(integ)
        db.commit()
    return {"status": "disconnected", "provider": provider}


# ── Helper: refresh token if expired ────────────────────────

def _ensure_valid_token(integ: UserIntegration, db: Session) -> str:
    """Refresh the access token if it's expired."""
    if integ.token_expiry and integ.token_expiry > datetime.datetime.utcnow():
        return integ.access_token

    if not integ.refresh_token:
        raise HTTPException(401, detail="Google token expired and no refresh token. Please reconnect.")

    resp = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
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


# ── Helper: get form data as rows ────────────────────────────

def _get_form_data(form_id: str, user: User, db: Session):
    """Retrieve form + responses and return (form, headers, rows)."""
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

    if not responses:
        raise HTTPException(400, detail="No responses to export")

    # Build headers from form questions
    questions = form.questions or []
    headers = ["Submitted At", "Respondent Email"]
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

    return form, headers, rows


# ── 5. Push to Google Drive ──────────────────────────────────

@router.post("/push-drive", response_model=PushResult)
def push_to_drive(
    data: PushToDriveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export form responses as a CSV file to the user's Google Drive."""
    integ = (
        db.query(UserIntegration)
        .filter(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == "google_drive",
            UserIntegration.is_active == True,
        )
        .first()
    )
    if not integ:
        raise HTTPException(400, detail="Google Drive is not connected. Please connect first.")

    access_token = _ensure_valid_token(integ, db)
    form, headers, rows = _get_form_data(data.form_id, current_user, db)

    # Build CSV content
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    csv_content = buffer.getvalue()

    file_name = data.file_name or f"{form.title or 'Form'}_Responses.csv"

    # Step 1: Find or create folder
    folder_id = None
    if data.folder_name:
        search_resp = http_requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "q": f"name='{data.folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                "spaces": "drive",
                "fields": "files(id, name)",
            },
        )
        files = search_resp.json().get("files", [])
        if files:
            folder_id = files[0]["id"]
        else:
            folder_meta = {
                "name": data.folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            create_resp = http_requests.post(
                "https://www.googleapis.com/drive/v3/files",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(folder_meta),
            )
            if create_resp.status_code in (200, 201):
                folder_id = create_resp.json()["id"]

    # Step 2: Upload CSV file
    metadata = {"name": file_name, "mimeType": "text/csv"}
    if folder_id:
        metadata["parents"] = [folder_id]

    # Multipart upload
    boundary = "foreform_boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Type: application/json; charset=UTF-8\r\n\r\n'
        f'{json.dumps(metadata)}\r\n'
        f"--{boundary}\r\n"
        f"Content-Type: text/csv\r\n\r\n"
        f"{csv_content}\r\n"
        f"--{boundary}--"
    )

    upload_resp = http_requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        data=body.encode("utf-8"),
    )

    if upload_resp.status_code not in (200, 201):
        raise HTTPException(500, detail=f"Drive upload failed: {upload_resp.text}")

    file_data = upload_resp.json()
    file_url = f"https://drive.google.com/file/d/{file_data['id']}/view"

    return PushResult(success=True, url=file_url, message=f"Exported {len(rows)} responses to Google Drive")


# ── 6. Push to Google Sheets ────────────────────────────────

@router.post("/push-sheets", response_model=PushResult)
def push_to_sheets(
    data: PushToSheetsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export form responses to a new Google Sheet in the user's account."""
    integ = (
        db.query(UserIntegration)
        .filter(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == "google_sheets",
            UserIntegration.is_active == True,
        )
        .first()
    )
    if not integ:
        raise HTTPException(400, detail="Google Sheets is not connected. Please connect first.")

    access_token = _ensure_valid_token(integ, db)
    form, headers, rows = _get_form_data(data.form_id, current_user, db)

    spreadsheet_name = data.spreadsheet_name or f"{form.title or 'Form'} — Responses"

    # Step 1: Create a new spreadsheet
    create_body = {
        "properties": {"title": spreadsheet_name},
        "sheets": [{"properties": {"title": "Responses"}}],
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

    # Step 2: Write data
    all_values = [headers] + rows
    update_body = {"values": all_values}
    update_resp = http_requests.put(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/Responses!A1"
        f"?valueInputOption=RAW",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(update_body),
    )

    if update_resp.status_code != 200:
        raise HTTPException(500, detail=f"Sheets data write failed: {update_resp.text}")

    # Step 3: Format header row (bold + freeze)
    format_body = {
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": 0,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
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

    sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    return PushResult(
        success=True,
        url=sheet_url,
        message=f"Exported {len(rows)} responses to Google Sheets",
    )
