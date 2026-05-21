from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from db import get_db
from models.task import Task, TaskActivity, TaskAssignee
from models.user import User
from schemas.task import TaskCreate, TaskUpdate, TaskOut
from auth.jwt import get_current_user

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])

@router.post("/", response_model=TaskOut)
def create_task(task_in: TaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task_data = task_in.model_dump(exclude={"assignee_emails"})
    new_task = Task(**task_data, user_id=current_user.id)
    
    # Handle multiple assignees
    assignee_emails = task_in.assignee_emails or []
    # Backward compat: if only assignee_email was provided, include it too
    if task_in.assignee_email and task_in.assignee_email not in assignee_emails:
        assignee_emails.append(task_in.assignee_email)
    
    for email in assignee_emails:
        email = email.strip()
        if email:
            new_task.assignees.append(TaskAssignee(email=email))
    
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return new_task

@router.get("/", response_model=List[TaskOut])
def get_tasks(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fetch tasks for the current user (created by or assigned to them)."""
    tasks = db.query(Task).filter(
        (Task.user_id == current_user.id) |
        (Task.assignee_email == current_user.email) |
        (Task.assignees.any(TaskAssignee.email == current_user.email))
    ).order_by(Task.created_at.desc()).all()
    return tasks

@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task

@router.put("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, task_in: TaskUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    update_data = task_in.model_dump(exclude_unset=True, exclude={"assignee_emails"})
    
    # Activity tracking for status changes
    if "status" in update_data and update_data["status"] == "done" and task.status != "done":
        activity = TaskActivity(
            task_id=task.id,
            action="marked task as done",
            user=current_user.full_name or "User"
        )
        if "attachment_url" in update_data and update_data["attachment_url"]:
            activity.action += " and uploaded a file"
        db.add(activity)

    for field, value in update_data.items():
        setattr(task, field, value)
    
    # Handle assignee_emails update (replace all assignees)
    if task_in.assignee_emails is not None:
        # Clear existing assignees
        task.assignees.clear()
        for email in task_in.assignee_emails:
            email = email.strip()
            if email:
                task.assignees.append(TaskAssignee(email=email))
        
        # Log the assignment activity
        if task_in.assignee_emails:
            names = ", ".join(task_in.assignee_emails)
            activity = TaskActivity(
                task_id=task.id,
                action=f"assigned task to {names}",
                user=current_user.full_name or "User"
            )
            db.add(activity)
        
    db.commit()
    db.refresh(task)
    return task

@router.delete("/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    db.delete(task)
    db.commit()
    return {"message": "Task deleted"}


# --- Additional endpoints ---

from pydantic import BaseModel

class TaskComment(BaseModel):
    text: str

@router.post("/{task_id}/comments", response_model=TaskOut)
def add_task_comment(task_id: str, comment: TaskComment, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    activity = TaskActivity(
        task_id=task.id,
        action=f"commented: {comment.text}",
        user=current_user.full_name or "User"
    )
    db.add(activity)
    db.commit()
    db.refresh(task)
    return task


class AssigneeUpdate(BaseModel):
    emails: List[str]

@router.put("/{task_id}/assignees", response_model=TaskOut)
def update_task_assignees(task_id: str, data: AssigneeUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Dedicated endpoint to replace all assignees on a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    # Clear existing and set new
    task.assignees.clear()
    added = []
    for email in data.emails:
        email = email.strip()
        if email:
            task.assignees.append(TaskAssignee(email=email))
            added.append(email)
    
    if added:
        activity = TaskActivity(
            task_id=task.id,
            action=f"assigned task to {', '.join(added)}",
            user=current_user.full_name or "User"
        )
        db.add(activity)
    
    db.commit()
    db.refresh(task)
    return task

@router.post("/{task_id}/assignees/add", response_model=TaskOut)
def add_task_assignee(task_id: str, data: AssigneeUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Add one or more assignees without removing existing ones."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    existing_emails = {a.email for a in task.assignees}
    added = []
    for email in data.emails:
        email = email.strip()
        if email and email not in existing_emails:
            task.assignees.append(TaskAssignee(email=email))
            added.append(email)
    
    if added:
        activity = TaskActivity(
            task_id=task.id,
            action=f"added assignee(s): {', '.join(added)}",
            user=current_user.full_name or "User"
        )
        db.add(activity)
    
    db.commit()
    db.refresh(task)
    return task

@router.post("/{task_id}/assignees/remove", response_model=TaskOut)
def remove_task_assignee(task_id: str, data: AssigneeUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Remove one or more assignees from a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    emails_to_remove = {e.strip() for e in data.emails}
    removed = []
    for assignee in list(task.assignees):
        if assignee.email in emails_to_remove:
            task.assignees.remove(assignee)
            removed.append(assignee.email)
    
    if removed:
        activity = TaskActivity(
            task_id=task.id,
            action=f"removed assignee(s): {', '.join(removed)}",
            user=current_user.full_name or "User"
        )
        db.add(activity)
    
    db.commit()
    db.refresh(task)
    return task
