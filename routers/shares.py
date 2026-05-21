from typing import List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from models.form import Form
from models.form_share import FormShare
from models.user import User
from schemas.share import ShareCreate, ShareOut
from auth.jwt import get_current_user
from services.resend_email import send_share_invitation_email

router = APIRouter(prefix="/api/forms", tags=["shares"])


@router.get("/{form_id}/shares", response_model=List[ShareOut])
def list_shares(
    form_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all shares for a form. Only the form owner can view."""
    form = (
        db.query(Form)
        .filter(Form.id == form_id, Form.created_by == current_user.email)
        .first()
    )
    if not form:
        raise HTTPException(status_code=404, detail="Form not found or access denied")
    return db.query(FormShare).filter(FormShare.form_id == form_id).all()


@router.post("/{form_id}/shares", response_model=ShareOut, status_code=201)
def create_share(
    form_id: str,
    data: ShareCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Share a form with another user. Only the form owner can share."""
    form = (
        db.query(Form)
        .filter(Form.id == form_id, Form.created_by == current_user.email)
        .first()
    )
    if not form:
        raise HTTPException(status_code=404, detail="Form not found or access denied")

    # Check if already shared with this email
    existing = (
        db.query(FormShare)
        .filter(FormShare.form_id == form_id, FormShare.shared_with_email == data.shared_with_email)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Form already shared with this user")

    share = FormShare(
        form_id=form_id,
        shared_with_email=data.shared_with_email,
        permission=data.permission.value,
        shared_by=current_user.email,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    background_tasks.add_task(
        send_share_invitation_email,
        share.shared_with_email,
        form.title,
        current_user.email,
        share.permission,
    )
    return share


@router.delete("/shares/{share_id}", status_code=204)
def delete_share(
    share_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a share. Only the form owner can remove shares."""
    share = db.query(FormShare).filter(FormShare.id == share_id).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    form = (
        db.query(Form)
        .filter(Form.id == share.form_id, Form.created_by == current_user.email)
        .first()
    )
    if not form:
        raise HTTPException(status_code=403, detail="Access denied")

    db.delete(share)
    db.commit()
    return None

@router.put("/shares/{share_id}", response_model=ShareOut)
def update_share(
    share_id: str,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    share = db.query(FormShare).filter(FormShare.id == share_id).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
        
    form = db.query(Form).filter(Form.id == share.form_id, Form.created_by == current_user.email).first()
    if not form:
        raise HTTPException(status_code=403, detail="Access denied")
        
    if "permission" in data:
        share.permission = data["permission"]
        
    db.commit()
    db.refresh(share)
    return share
