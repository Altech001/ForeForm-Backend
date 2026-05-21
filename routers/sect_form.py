from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db import get_db
from models.form import Form
from models.form_section import FormSection
from models.user import User
from schemas.form_section import FormSectionCreate, FormSectionUpdate, FormSectionOut
from auth.jwt import get_current_user

router = APIRouter(prefix="/api/sections", tags=["sections"])


@router.get("/form/{form_id}", response_model=List[FormSectionOut])
def list_form_sections(form_id: str, db: Session = Depends(get_db)):
    """List all sections for a specific form."""
    return db.query(FormSection).filter(FormSection.form_id == form_id).order_by(FormSection.order).all()


@router.post("/form/{form_id}", response_model=FormSectionOut, status_code=201)
def create_section(
    form_id: str,
    data: FormSectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new section in a form."""
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    
    # Check permission (owner or editor)
    if form.created_by != current_user.email:
        from models.form_share import FormShare
        has_edit = db.query(FormShare).filter(
            FormShare.form_id == form_id,
            FormShare.shared_with_email == current_user.email,
            FormShare.permission == "editor"
        ).first() is not None
        if not has_edit:
            raise HTTPException(status_code=403, detail="Access denied")

    section_data = data.model_dump()
    section_data["questions"] = [q.model_dump() for q in data.questions]
    
    section = FormSection(**section_data, form_id=form_id)
    db.add(section)
    db.commit()
    db.refresh(section)
    return section


@router.put("/{section_id}", response_model=FormSectionOut)
def update_section(
    section_id: str,
    data: FormSectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a section."""
    section = db.query(FormSection).filter(FormSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
        
    form = section.form
    if form.created_by != current_user.email:
         from models.form_share import FormShare
         has_edit = db.query(FormShare).filter(
            FormShare.form_id == form.id,
            FormShare.shared_with_email == current_user.email,
            FormShare.permission == "editor"
        ).first() is not None
         if not has_edit:
             raise HTTPException(status_code=403, detail="Access denied")

    update_data = data.model_dump(exclude_unset=True)
    if "questions" in update_data and data.questions is not None:
        update_data["questions"] = [q.model_dump() for q in data.questions]

    for key, value in update_data.items():
        setattr(section, key, value)

    db.commit()
    db.refresh(section)
    return section


@router.delete("/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_section(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a section."""
    section = db.query(FormSection).filter(FormSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
        
    form = section.form
    if form.created_by != current_user.email:
        raise HTTPException(status_code=403, detail="Access denied")

    db.delete(section)
    db.commit()
    return None


@router.post("/form/{form_id}/reorder", response_model=List[FormSectionOut])
def reorder_sections(
    form_id: str,
    section_ids: List[str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reorder sections in a form."""
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form or form.created_by != current_user.email:
        raise HTTPException(status_code=403, detail="Access denied or form not found")
        
    for index, s_id in enumerate(section_ids):
        db.query(FormSection).filter(FormSection.id == s_id, FormSection.form_id == form_id).update({"order": index})
    
    db.commit()
    return db.query(FormSection).filter(FormSection.id.in_(section_ids)).order_by(FormSection.order).all()
