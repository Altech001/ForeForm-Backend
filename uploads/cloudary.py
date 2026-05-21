#type: ignore

import os
import cloudinary
import cloudinary.uploader
from config import settings

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)

def upload_to_cloudary(file_content: bytes, filename: str) -> str:
    """
    Uploads a file to Cloudinary and returns the secure URL.
    Supports images, videos, and raw files (pdfs, docs, etc.).
    """
    ext = os.path.splitext(filename)[1].lower()
    
    # Identify resource_type
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}:
        resource_type = "image"
    elif ext in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav"}:
        resource_type = "video"
    else:
        resource_type = "raw"

    response = cloudinary.uploader.upload(
        file_content,
        resource_type=resource_type,
        use_filename=True,
        unique_filename=True
    )
    return response.get("secure_url")