from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from db import get_db
from models.form import Form
from models.form_response import FormResponse
from models.user import User
from schemas.response import ResponseCreate, ResponseOut
from auth.jwt import get_current_user
from services.resend_email import send_response_confirmation_email
from services.quiz import calculate_score

router = APIRouter(prefix="/api", tags=["responses"])


# ── List all responses for a form (authenticated) ───────────

@router.get("/forms/{form_id}/responses", response_model=List[ResponseOut])
def list_responses(
    form_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all responses for a form. Owner or any shared user (editor/viewer) can view."""
    from models.form_share import FormShare
    
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
        
    is_owner = form.created_by == current_user.email
    has_share_access = db.query(FormShare).filter(
        FormShare.form_id == form_id, 
        FormShare.shared_with_email == current_user.email
    ).first() is not None
    
    if not (is_owner or has_share_access):
        raise HTTPException(status_code=403, detail="Access denied")
    return (
        db.query(FormResponse)
        .filter(FormResponse.form_id == form_id)
        .order_by(FormResponse.created_date.desc())
        .all()
    )


# ── Submit a response (PUBLIC — no auth) ─────────────────────

@router.post("/forms/{form_id}/responses", response_model=ResponseOut, status_code=201)
def submit_response(
    form_id: str, 
    data: ResponseCreate, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Submit a form response — **PUBLIC** (no auth required).
    Side effects: increments Form.response_count by 1.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form or form.status != "published":
        raise HTTPException(status_code=403, detail="Form not accepting responses")

    response_data = data.model_dump()
    # Serialize answers list[AnswerItem] → list[dict] for JSON column
    if response_data.get("answers"):
        response_data["answers"] = [a.model_dump() for a in data.answers]

    answer_values = {
        answer.get("question_id"): answer.get("answer")
        for answer in response_data.get("answers", [])
    }
    score = calculate_score(form, answer_values)
    quiz = form.quiz or {}

    if score:
        scored_by_question = {
            scored["question_id"]: scored
            for scored in score["scored_answers"]
        }
        for answer in response_data.get("answers", []):
            scored = scored_by_question.get(answer.get("question_id"))
            if scored:
                answer["is_correct"] = scored["is_correct"]
                answer["points_earned"] = scored["points_earned"]
                answer["points_possible"] = scored["points_possible"]

        response_data["quiz_score"] = score["earned"]
        response_data["quiz_max_score"] = score["possible"]
        response_data["quiz_percent"] = score["percent"]
        response_data["grades_released"] = quiz.get("release_grades") != "manual"

    response = FormResponse(form_id=form_id, **response_data)
    db.add(response)

    # Increment response count
    form.response_count = (form.response_count or 0) + 1

    db.commit()
    db.refresh(response)
    
    # Send confirmation email to respondent_email using Resend
    if response.respondent_email:
        background_tasks.add_task(
            send_response_confirmation_email,
            response.respondent_email,
            form.title,
            response_data.get("answers", []),
            response.respondent_name,
            (form.branding or {}).get("organization"),
        )

    return response


# ── Get a single response (authenticated) ────────────────────

@router.get("/responses/{response_id}", response_model=ResponseOut)
def get_response(
    response_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single response. Owner or any shared user can view."""
    from models.form_share import FormShare
    
    response = db.query(FormResponse).filter(FormResponse.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
        
    # Verify the current user owns or has share access to parent form
    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
        
    is_owner = form.created_by == current_user.email
    has_share_access = db.query(FormShare).filter(
        FormShare.form_id == form.id, 
        FormShare.shared_with_email == current_user.email
    ).first() is not None
    
    if not (is_owner or has_share_access):
        raise HTTPException(status_code=403, detail="Access denied")
    return response


# ── Delete a response (authenticated) ────────────────────────

@router.delete("/responses/{response_id}", status_code=204)
def delete_response(
    response_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a response. Owner or editor can delete."""
    from models.form_share import FormShare
    
    response = db.query(FormResponse).filter(FormResponse.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
        
    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
         raise HTTPException(status_code=404, detail="Form not found")
         
    is_owner = form.created_by == current_user.email
    has_edit_access = db.query(FormShare).filter(
        FormShare.form_id == form.id, 
        FormShare.shared_with_email == current_user.email,
        FormShare.permission == "editor"
    ).first() is not None
    
    if not (is_owner or has_edit_access):
        raise HTTPException(status_code=403, detail="Access denied")
    db.delete(response)
    form.response_count = max((form.response_count or 1) - 1, 0)
    db.commit()
    return None


@router.patch("/responses/{response_id}/release-grades", response_model=ResponseOut)
def release_grades(
    response_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually release grades for a quiz response. Owner or editor can release."""
    from models.form_share import FormShare

    response = db.query(FormResponse).filter(FormResponse.id == response_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")

    form = db.query(Form).filter(Form.id == response.form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    is_owner = form.created_by == current_user.email
    has_edit_access = db.query(FormShare).filter(
        FormShare.form_id == form.id,
        FormShare.shared_with_email == current_user.email,
        FormShare.permission == "editor"
    ).first() is not None

    if not (is_owner or has_edit_access):
        raise HTTPException(status_code=403, detail="Access denied")

    response.grades_released = True
    db.commit()
    db.refresh(response)
    return response
