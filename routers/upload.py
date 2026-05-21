import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from uploads.cloudary import upload_to_cloudary

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico",  # images
    ".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc", ".txt", ".pptx", ".ppt",  # documents
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
):
    """
    Upload a file (logo, PDF, spreadsheet, etc.) to Cloudinary.
    Returns { file_url: "https://res.cloudinary.com/..." }.
    """
    # Validate extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type '{ext}' not allowed")

    # Read and validate size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 10 MB limit")

    try:
        secure_url = upload_to_cloudary(contents, file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload to Cloudinary failed: {str(e)}")

    return {"file_url": secure_url}
