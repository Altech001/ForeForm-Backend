"""
Drive Explorer & Smart File Upload Router
──────────────────────────────────────────
Provides:
  • POST /api/drive/upload           — smart upload: text/docs → Drive, media → Cloudinary (or user choice)
  • GET  /api/drive/files            — list files in user's Drive
  • GET  /api/drive/files/{file_id}  — get file metadata
  • POST /api/drive/folder           — create a folder in Drive
  • GET  /api/drive/folders          — list folders in Drive
  • DELETE /api/drive/files/{file_id} — delete a file from Drive
  • POST /api/drive/upload-raw       — upload raw file bytes to Drive (any file type)
  • GET  /api/drive/search           — search files by name in Drive
  • GET  /api/drive/download/{file_id} — get download link for a Drive file

Upload strategy:
  • .docx, .doc, .txt, .md, .rtf, .odt, .csv, .pdf → Google Drive
  • .png, .jpg, .jpeg, .gif, .webp, .svg, .mp4, .mp3, etc. → Cloudinary
  • User can override with ?destination=drive or ?destination=cloudinary
"""

import os
import json
import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form as FastAPIForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from config import settings
from models.user import User
from models.user_integration import UserIntegration
from auth.jwt import get_current_user
from uploads.cloudary import upload_to_cloudary

import requests as http_requests

router = APIRouter(prefix="/api/drive", tags=["drive-explorer"])


# ── File type classification ────────────────────────────────

DRIVE_EXTENSIONS = {
    ".docx", ".doc", ".txt", ".md", ".rtf", ".odt",
    ".csv", ".tsv", ".pdf", ".tex", ".html", ".htm",
    ".xml", ".json", ".yaml", ".yml", ".log",
}

CLOUDINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".bmp", ".ico", ".tiff",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".mp3", ".wav", ".ogg", ".flac", ".aac",
}

MIME_MAP = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".rtf": "application/rtf",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".xml": "application/xml",
    ".json": "application/json",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".log": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
}

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


# ── Schemas ──────────────────────────────────────────────────

class UploadResult(BaseModel):
    success: bool
    destination: str  # "drive" | "cloudinary"
    file_url: str
    file_name: str
    file_id: Optional[str] = None
    mime_type: Optional[str] = None
    message: str


class DriveFileInfo(BaseModel):
    id: str
    name: str
    mime_type: str
    size: Optional[str] = None
    created_time: Optional[str] = None
    modified_time: Optional[str] = None
    web_view_link: Optional[str] = None
    web_content_link: Optional[str] = None
    icon_link: Optional[str] = None


class FolderCreateRequest(BaseModel):
    name: str
    parent_id: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────

def _get_drive_token(user: User, db: Session) -> str:
    """Get a valid Google Drive access token."""
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
        # Fallback: try google_sheets (has drive.file scope)
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
        raise HTTPException(400, detail="Google Drive is not connected. Please connect first.")

    return _ensure_valid_token(integ, db)


def _ensure_valid_token(integ: UserIntegration, db: Session) -> str:
    """Refresh the access token if it's expired."""
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


def _classify_destination(ext: str) -> str:
    """Determine default upload destination based on file extension."""
    if ext in DRIVE_EXTENSIONS:
        return "drive"
    return "cloudinary"


def _upload_to_drive(
    access_token: str,
    file_content: bytes,
    file_name: str,
    mime_type: str,
    folder_id: Optional[str] = None,
) -> dict:
    """Upload a file to Google Drive using multipart upload."""
    metadata = {"name": file_name, "mimeType": mime_type}
    if folder_id:
        metadata["parents"] = [folder_id]

    boundary = "foreform_drive_upload"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n"
        f"Content-Transfer-Encoding: binary\r\n\r\n"
    ).encode("utf-8") + file_content + f"\r\n--{boundary}--".encode("utf-8")

    resp = http_requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,mimeType,webViewLink,webContentLink",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        data=body,
    )

    if resp.status_code not in (200, 201):
        raise HTTPException(500, detail=f"Drive upload failed: {resp.text}")

    return resp.json()


# ═══════════════════════════════════════════════════════════════
# 1. SMART UPLOAD — Auto-route to Drive or Cloudinary
# ═══════════════════════════════════════════════════════════════

@router.post("/upload", response_model=UploadResult)
async def smart_upload(
    file: UploadFile = File(...),
    destination: Optional[str] = FastAPIForm(None),  # "drive" | "cloudinary" | None (auto)
    folder_id: Optional[str] = FastAPIForm(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Smart file upload:
    • Text/document files (.docx, .txt, .pdf, etc.) → Google Drive
    • Media files (.png, .jpg, .mp4, etc.) → Cloudinary
    • User can override with destination parameter
    """
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(400, detail="File exceeds 25 MB limit")

    filename = file.filename or "untitled"
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_MAP.get(ext, file.content_type or "application/octet-stream")

    # Determine destination
    if destination and destination in ("drive", "cloudinary"):
        target = destination
    else:
        target = _classify_destination(ext)

    if target == "drive":
        # Upload to Google Drive
        try:
            access_token = _get_drive_token(current_user, db)
        except HTTPException:
            # If Drive not connected, fall back to Cloudinary
            target = "cloudinary"

    if target == "drive":
        file_data = _upload_to_drive(access_token, contents, filename, mime, folder_id)
        file_url = file_data.get("webViewLink") or f"https://drive.google.com/file/d/{file_data['id']}/view"

        return UploadResult(
            success=True,
            destination="drive",
            file_url=file_url,
            file_name=filename,
            file_id=file_data["id"],
            mime_type=mime,
            message=f"Uploaded '{filename}' to Google Drive",
        )
    else:
        # Upload to Cloudinary
        try:
            secure_url = upload_to_cloudary(contents, filename)
        except Exception as e:
            raise HTTPException(500, detail=f"Cloudinary upload failed: {str(e)}")

        return UploadResult(
            success=True,
            destination="cloudinary",
            file_url=secure_url,
            file_name=filename,
            mime_type=mime,
            message=f"Uploaded '{filename}' to Cloudinary",
        )


# ═══════════════════════════════════════════════════════════════
# 2. UPLOAD RAW — Always upload to Drive
# ═══════════════════════════════════════════════════════════════

@router.post("/upload-raw", response_model=UploadResult)
async def upload_raw_to_drive(
    file: UploadFile = File(...),
    folder_id: Optional[str] = FastAPIForm(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload any file directly to Google Drive (no auto-routing)."""
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(400, detail="File exceeds 25 MB limit")

    filename = file.filename or "untitled"
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_MAP.get(ext, file.content_type or "application/octet-stream")

    access_token = _get_drive_token(current_user, db)
    file_data = _upload_to_drive(access_token, contents, filename, mime, folder_id)
    file_url = file_data.get("webViewLink") or f"https://drive.google.com/file/d/{file_data['id']}/view"

    return UploadResult(
        success=True,
        destination="drive",
        file_url=file_url,
        file_name=filename,
        file_id=file_data["id"],
        mime_type=mime,
        message=f"Uploaded '{filename}' to Google Drive",
    )


# ═══════════════════════════════════════════════════════════════
# 3. LIST FILES — Browse Drive contents
# ═══════════════════════════════════════════════════════════════

@router.get("/files")
def list_drive_files(
    folder_id: Optional[str] = Query(None, description="Folder ID to list (root if None)"),
    page_size: int = Query(20, ge=1, le=100),
    page_token: Optional[str] = Query(None),
    mime_type: Optional[str] = Query(None, description="Filter by MIME type"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List files and folders in the user's Google Drive."""
    access_token = _get_drive_token(current_user, db)

    q_parts = ["trashed=false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    if mime_type:
        q_parts.append(f"mimeType='{mime_type}'")

    params = {
        "q": " and ".join(q_parts),
        "pageSize": page_size,
        "fields": "nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, webViewLink, webContentLink, iconLink, parents)",
        "orderBy": "folder,modifiedTime desc",
    }
    if page_token:
        params["pageToken"] = page_token

    resp = http_requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Failed to list files: {resp.text}")

    result = resp.json()
    files = result.get("files", [])

    return {
        "files": [
            {
                "id": f["id"],
                "name": f["name"],
                "mime_type": f["mimeType"],
                "is_folder": f["mimeType"] == "application/vnd.google-apps.folder",
                "size": f.get("size"),
                "created_time": f.get("createdTime"),
                "modified_time": f.get("modifiedTime"),
                "web_view_link": f.get("webViewLink"),
                "web_content_link": f.get("webContentLink"),
                "icon_link": f.get("iconLink"),
                "parents": f.get("parents", []),
            }
            for f in files
        ],
        "next_page_token": result.get("nextPageToken"),
    }


# ═══════════════════════════════════════════════════════════════
# 4. FILE DETAIL — Get metadata for a specific file
# ═══════════════════════════════════════════════════════════════

@router.get("/files/{file_id}")
def get_file_detail(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed metadata for a specific Drive file."""
    access_token = _get_drive_token(current_user, db)

    resp = http_requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "fields": "id, name, mimeType, size, createdTime, modifiedTime, webViewLink, webContentLink, iconLink, parents, description, starred"
        },
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Failed to get file info: {resp.text}")

    f = resp.json()
    return {
        "id": f["id"],
        "name": f["name"],
        "mime_type": f.get("mimeType"),
        "size": f.get("size"),
        "created_time": f.get("createdTime"),
        "modified_time": f.get("modifiedTime"),
        "web_view_link": f.get("webViewLink"),
        "web_content_link": f.get("webContentLink"),
        "icon_link": f.get("iconLink"),
        "parents": f.get("parents", []),
        "description": f.get("description"),
        "starred": f.get("starred", False),
    }


# ═══════════════════════════════════════════════════════════════
# 5. CREATE FOLDER
# ═══════════════════════════════════════════════════════════════

@router.post("/folder")
def create_folder(
    data: FolderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new folder in Google Drive."""
    access_token = _get_drive_token(current_user, db)

    metadata = {
        "name": data.name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if data.parent_id:
        metadata["parents"] = [data.parent_id]

    resp = http_requests.post(
        "https://www.googleapis.com/drive/v3/files",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(metadata),
    )

    if resp.status_code not in (200, 201):
        raise HTTPException(500, detail=f"Folder creation failed: {resp.text}")

    folder = resp.json()
    return {
        "success": True,
        "folder_id": folder["id"],
        "name": folder["name"],
        "message": f"Folder '{data.name}' created",
    }


# ═══════════════════════════════════════════════════════════════
# 6. LIST FOLDERS
# ═══════════════════════════════════════════════════════════════

@router.get("/folders")
def list_folders(
    parent_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List folders in the user's Drive for folder picker."""
    access_token = _get_drive_token(current_user, db)

    q_parts = [
        "mimeType='application/vnd.google-apps.folder'",
        "trashed=false",
    ]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")

    resp = http_requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": " and ".join(q_parts),
            "pageSize": 100,
            "fields": "files(id, name, createdTime, modifiedTime)",
            "orderBy": "name",
        },
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Failed to list folders: {resp.text}")

    folders = resp.json().get("files", [])
    return {
        "folders": [
            {
                "id": f["id"],
                "name": f["name"],
                "created_time": f.get("createdTime"),
                "modified_time": f.get("modifiedTime"),
            }
            for f in folders
        ]
    }


# ═══════════════════════════════════════════════════════════════
# 7. DELETE FILE
# ═══════════════════════════════════════════════════════════════

@router.delete("/files/{file_id}")
def delete_drive_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a file from Google Drive (moves to trash)."""
    access_token = _get_drive_token(current_user, db)

    # Move to trash instead of permanent delete
    resp = http_requests.patch(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps({"trashed": True}),
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Failed to delete file: {resp.text}")

    return {"success": True, "message": "File moved to trash"}


# ═══════════════════════════════════════════════════════════════
# 8. SEARCH FILES
# ═══════════════════════════════════════════════════════════════

@router.get("/search")
def search_drive_files(
    query: str = Query(..., min_length=1, description="Search query"),
    page_size: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search files by name in the user's Google Drive."""
    access_token = _get_drive_token(current_user, db)

    resp = http_requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": f"name contains '{query}' and trashed=false",
            "pageSize": page_size,
            "fields": "files(id, name, mimeType, size, modifiedTime, webViewLink, iconLink)",
            "orderBy": "modifiedTime desc",
        },
    )

    if resp.status_code != 200:
        raise HTTPException(500, detail=f"Search failed: {resp.text}")

    files = resp.json().get("files", [])
    return {
        "query": query,
        "results": [
            {
                "id": f["id"],
                "name": f["name"],
                "mime_type": f["mimeType"],
                "is_folder": f["mimeType"] == "application/vnd.google-apps.folder",
                "size": f.get("size"),
                "modified_time": f.get("modifiedTime"),
                "web_view_link": f.get("webViewLink"),
                "icon_link": f.get("iconLink"),
            }
            for f in files
        ],
        "total": len(files),
    }


# ═══════════════════════════════════════════════════════════════
# 9. DOWNLOAD LINK
# ═══════════════════════════════════════════════════════════════

@router.get("/download/{file_id}")
def get_download_link(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a temporary download link for a Drive file."""
    access_token = _get_drive_token(current_user, db)

    # Get file metadata to check type
    meta_resp = http_requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"fields": "id, name, mimeType, webContentLink"},
    )

    if meta_resp.status_code != 200:
        raise HTTPException(500, detail=f"Failed to get file info: {meta_resp.text}")

    meta = meta_resp.json()
    download_url = meta.get("webContentLink")

    if not download_url:
        # For Google Docs/Sheets/Slides, provide export URL
        mime = meta.get("mimeType", "")
        if "document" in mime:
            download_url = f"https://docs.google.com/document/d/{file_id}/export?format=docx"
        elif "spreadsheet" in mime:
            download_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
        elif "presentation" in mime:
            download_url = f"https://docs.google.com/presentation/d/{file_id}/export?format=pptx"
        else:
            download_url = f"https://drive.google.com/uc?id={file_id}&export=download"

    return {
        "file_id": file_id,
        "name": meta.get("name"),
        "mime_type": meta.get("mimeType"),
        "download_url": download_url,
    }
