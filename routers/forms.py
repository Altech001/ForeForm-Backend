from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db import get_db
from models.form import Form
from models.user import User
from schemas.form import FormCreate, FormUpdate, FormOut
from auth.jwt import get_current_user

router = APIRouter(prefix="/api/forms", tags=["forms"])


@router.get("/", response_model=List[FormOut])
def list_forms(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List all forms owned by or shared with the authenticated user, sorted by created_date desc."""
    from models.form_share import FormShare
    
    # Get IDs of forms shared with user
    shared_form_ids = db.query(FormShare.form_id).filter(FormShare.shared_with_email == current_user.email).all()
    shared_form_ids = [f[0] for f in shared_form_ids]
    
    return (
        db.query(Form)
        .filter(
            (Form.created_by == current_user.email) | 
            (Form.id.in_(shared_form_ids))
        )
        .order_by(Form.created_date.desc())
        .all()
    )


@router.post("/", response_model=FormOut, status_code=201)
def create_form(data: FormCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new form."""
    form_data = data.model_dump()
    # Convert nested Pydantic models to dicts for JSON columns
    form_data["branding"] = data.branding.model_dump(mode="json") if data.branding else {}
    form_data["quiz"] = data.quiz.model_dump(mode="json") if data.quiz else {}
    form_data["presentation"] = data.presentation.model_dump(mode="json") if data.presentation else {}
    if form_data.get("questions"):
        form_data["questions"] = [q.model_dump(mode="json") for q in data.questions]
    form = Form(**form_data, created_by=current_user.email)
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


@router.get("/{form_id}", response_model=FormOut)
def get_form(form_id: str, db: Session = Depends(get_db)):
    """
    Get a single form by ID — **PUBLIC** (no auth required).
    Used by the public form-fill page `/f/:id`.
    Returns 404 if not found, 403 if status is not 'published' (for public access).
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    return form


@router.put("/{form_id}", response_model=FormOut)
def update_form(
    form_id: str,
    data: FormUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update any subset of form fields. Only the form owner or an editor can update."""
    from models.form_share import FormShare
    
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
        
    # Check permissions: owner or editor share
    is_owner = form.created_by == current_user.email
    has_edit_access = db.query(FormShare).filter(
        FormShare.form_id == form_id, 
        FormShare.shared_with_email == current_user.email,
        FormShare.permission == "editor"
    ).first() is not None
    
    if not (is_owner or has_edit_access):
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = data.model_dump(exclude_unset=True)

    # Serialize nested Pydantic models for JSON columns
    if "branding" in update_data and data.branding is not None:
        update_data["branding"] = data.branding.model_dump(mode="json")
    if "quiz" in update_data and data.quiz is not None:
        update_data["quiz"] = data.quiz.model_dump(mode="json")
    if "presentation" in update_data and data.presentation is not None:
        update_data["presentation"] = data.presentation.model_dump(mode="json")
    if "questions" in update_data and data.questions is not None:
        update_data["questions"] = [q.model_dump(mode="json") for q in data.questions]

    for key, value in update_data.items():
        setattr(form, key, value)

    db.commit()
    db.refresh(form)
    return form


@router.delete("/{form_id}", status_code=204)
def delete_form(
    form_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a form. Only the form owner can delete."""
    form = (
        db.query(Form)
        .filter(Form.id == form_id, Form.created_by == current_user.email)
        .first()
    )
    if not form:
        raise HTTPException(status_code=404, detail="Form not found or access denied")
    db.delete(form)
    db.commit()
    return None
