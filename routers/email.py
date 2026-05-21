from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import List, Optional

from auth.jwt import get_current_user
from models.user import User
from services.resend_email import send_email

router = APIRouter(prefix="/api/email", tags=["email"])


class SendEmailRequest(BaseModel):
    to: List[EmailStr]
    subject: str
    html: Optional[str] = None
    body: Optional[str] = None


@router.post("/send")
def send_app_email(data: SendEmailRequest, current_user: User = Depends(get_current_user)):
    html = data.html or data.body
    if not html:
        raise HTTPException(status_code=400, detail="Provide either html or body")

    sent = send_email(
        [str(email) for email in data.to],
        data.subject,
        html,
        reply_to=current_user.email,
    )
    if not sent:
        raise HTTPException(status_code=500, detail="Email could not be sent")
    return {"sent": True}
