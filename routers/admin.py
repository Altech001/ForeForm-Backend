"""
Admin Dashboard & User Management Router
──────────────────────────────────────────
Provides:
  • GET  /api/admin/dashboard         — aggregate stats + recent activity
  • GET  /api/admin/users             — paginated user list with search & filters
  • GET  /api/admin/users/{user_id}   — detailed user profile (forms, integrations, etc.)
  • PATCH /api/admin/users/{user_id}/role  — promote / demote a user
  • PATCH /api/admin/users/{user_id}  — update user details
  • DELETE /api/admin/users/{user_id} — delete a user and all owned data
  • POST /api/admin/users/bulk-role   — bulk role update
  • GET  /api/admin/activity-log      — admin audit trail
  • GET  /api/admin/forms             — all forms across all users (admin view)
  • GET  /api/admin/responses/recent  — most recent responses across all forms

All endpoints require the requesting user to have role='admin'.
"""

import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date

from db import get_db
from models.user import User
from models.form import Form
from models.form_response import FormResponse
from models.task import Task
from models.user_integration import UserIntegration
from models.admin_activity_log import AdminActivityLog
from auth.jwt import get_current_user
from schemas.admin import (
    DashboardStats,
    DashboardDetail,
    AdminUserOut,
    UserRoleUpdate,
    AdminUserUpdate,
    AdminActivityLog as AdminActivityLogSchema,
    BulkRoleUpdate,
    BulkActionResult,
    UserGrowthPoint,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Helper: require admin role ───────────────────────────────

def _require_admin(user: User):
    """Raise 403 if the user is not an admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _log_action(
    db: Session,
    admin_email: str,
    action: str,
    target_email: str = None,
    details: str = None,
):
    """Record an admin action in the audit log."""
    log = AdminActivityLog(
        admin_email=admin_email,
        action=action,
        target_user_email=target_email,
        details=details,
    )
    db.add(log)
    db.commit()


# ═══════════════════════════════════════════════════════════════
# 1. DASHBOARD
# ═══════════════════════════════════════════════════════════════

@router.get("/dashboard")
def admin_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return aggregate statistics for the admin dashboard."""
    _require_admin(current_user)

    today = datetime.date.today()

    total_users = db.query(func.count(User.id)).scalar() or 0
    total_forms = db.query(func.count(Form.id)).scalar() or 0
    total_responses = db.query(func.count(FormResponse.id)).scalar() or 0
    total_tasks = db.query(func.count(Task.id)).scalar() or 0
    active_integrations = (
        db.query(func.count(UserIntegration.id))
        .filter(UserIntegration.is_active == True)
        .scalar()
        or 0
    )

    users_today = (
        db.query(func.count(User.id))
        .filter(cast(User.created_date, Date) == today)
        .scalar()
        or 0
    )
    responses_today = (
        db.query(func.count(FormResponse.id))
        .filter(cast(FormResponse.created_date, Date) == today)
        .scalar()
        or 0
    )
    forms_today = (
        db.query(func.count(Form.id))
        .filter(cast(Form.created_date, Date) == today)
        .scalar()
        or 0
    )

    stats = DashboardStats(
        total_users=total_users,
        total_forms=total_forms,
        total_responses=total_responses,
        total_tasks=total_tasks,
        active_integrations=active_integrations,
        users_today=users_today,
        responses_today=responses_today,
        forms_today=forms_today,
    )

    # Recent users (last 10)
    recent_users = (
        db.query(User)
        .order_by(User.created_date.desc())
        .limit(10)
        .all()
    )
    recent_users_out = [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "created_date": u.created_date.isoformat() if u.created_date else None,
        }
        for u in recent_users
    ]

    # User growth — last 30 days
    thirty_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=30)
    growth_query = (
        db.query(
            cast(User.created_date, Date).label("day"),
            func.count(User.id).label("cnt"),
        )
        .filter(User.created_date >= thirty_days_ago)
        .group_by(cast(User.created_date, Date))
        .order_by(cast(User.created_date, Date))
        .all()
    )
    user_growth = [
        UserGrowthPoint(date=str(row.day), count=row.cnt) for row in growth_query
    ]

    return DashboardDetail(
        stats=stats,
        recent_users=recent_users_out,
        user_growth=user_growth,
    )


# ═══════════════════════════════════════════════════════════════
# 2. USER LIST (paginated, searchable)
# ═══════════════════════════════════════════════════════════════

@router.get("/users")
def list_users(
    search: Optional[str] = Query(None, description="Search by name or email"),
    role: Optional[str] = Query(None, description="Filter by role"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return paginated list of all users with enrichment counts."""
    _require_admin(current_user)

    query = db.query(User)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (User.email.ilike(pattern)) | (User.full_name.ilike(pattern))
        )
    if role:
        query = query.filter(User.role == role)

    total = query.count()
    users = (
        query.order_by(User.created_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    results = []
    for u in users:
        form_count = db.query(func.count(Form.id)).filter(Form.created_by == u.email).scalar() or 0
        resp_count = (
            db.query(func.count(FormResponse.id))
            .join(Form, FormResponse.form_id == Form.id)
            .filter(Form.created_by == u.email)
            .scalar()
            or 0
        )
        integ_count = (
            db.query(func.count(UserIntegration.id))
            .filter(UserIntegration.user_id == u.id, UserIntegration.is_active == True)
            .scalar()
            or 0
        )
        results.append(
            AdminUserOut(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=u.role or "user",
                created_date=u.created_date,
                form_count=form_count,
                response_count=resp_count,
                integration_count=integ_count,
            )
        )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "users": results,
    }


# ═══════════════════════════════════════════════════════════════
# 3. USER DETAIL
# ═══════════════════════════════════════════════════════════════

@router.get("/users/{user_id}")
def get_user_detail(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed information about a specific user."""
    _require_admin(current_user)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")

    forms = db.query(Form).filter(Form.created_by == user.email).all()
    integrations = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == user.id)
        .all()
    )
    total_responses = (
        db.query(func.count(FormResponse.id))
        .join(Form, FormResponse.form_id == Form.id)
        .filter(Form.created_by == user.email)
        .scalar()
        or 0
    )

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role or "user",
            "created_date": user.created_date.isoformat() if user.created_date else None,
        },
        "forms": [
            {
                "id": f.id,
                "title": f.title,
                "status": f.status,
                "response_count": f.response_count or 0,
                "created_date": f.created_date.isoformat() if f.created_date else None,
            }
            for f in forms
        ],
        "integrations": [
            {
                "provider": i.provider,
                "connected_email": i.connected_email,
                "is_active": i.is_active,
                "created_date": i.created_date.isoformat() if i.created_date else None,
            }
            for i in integrations
        ],
        "total_responses": total_responses,
        "total_forms": len(forms),
    }


# ═══════════════════════════════════════════════════════════════
# 4. ROLE MANAGEMENT — Promote / Demote
# ═══════════════════════════════════════════════════════════════

@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: str,
    data: UserRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Promote or demote a user. Cannot change your own role."""
    _require_admin(current_user)

    if data.role not in ("admin", "user"):
        raise HTTPException(400, detail="Role must be 'admin' or 'user'")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(400, detail="You cannot change your own role")

    old_role = user.role
    user.role = data.role
    db.commit()
    db.refresh(user)

    _log_action(
        db,
        admin_email=current_user.email,
        action=f"role_change:{old_role}->{data.role}",
        target_email=user.email,
        details=f"Changed role from '{old_role}' to '{data.role}'",
    )

    return {
        "success": True,
        "user_id": user.id,
        "email": user.email,
        "old_role": old_role,
        "new_role": data.role,
        "message": f"User {user.email} role updated to '{data.role}'",
    }


# ═══════════════════════════════════════════════════════════════
# 5. UPDATE USER DETAILS
# ═══════════════════════════════════════════════════════════════

@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    data: AdminUserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update user details (name, email, role)."""
    _require_admin(current_user)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.email is not None:
        existing = db.query(User).filter(User.email == data.email, User.id != user_id).first()
        if existing:
            raise HTTPException(400, detail="Email already taken by another user")
        user.email = data.email
    if data.role is not None:
        if data.role not in ("admin", "user"):
            raise HTTPException(400, detail="Role must be 'admin' or 'user'")
        if user.id == current_user.id and data.role != current_user.role:
            raise HTTPException(400, detail="You cannot change your own role")
        user.role = data.role

    db.commit()
    db.refresh(user)

    _log_action(
        db,
        admin_email=current_user.email,
        action="update_user",
        target_email=user.email,
        details=f"Updated user details: {data.model_dump(exclude_unset=True)}",
    )

    return {
        "success": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role or "user",
        },
    }


# ═══════════════════════════════════════════════════════════════
# 6. DELETE USER
# ═══════════════════════════════════════════════════════════════

@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a user and all their owned forms/responses."""
    _require_admin(current_user)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(400, detail="You cannot delete your own account from admin panel")

    user_email = user.email

    # Delete user's forms (cascade deletes responses & shares)
    user_forms = db.query(Form).filter(Form.created_by == user_email).all()
    for f in user_forms:
        db.delete(f)

    # Delete user's integrations
    db.query(UserIntegration).filter(UserIntegration.user_id == user.id).delete()

    # Delete user's tasks
    db.query(Task).filter(Task.created_by == user.id).delete()

    db.delete(user)
    db.commit()

    _log_action(
        db,
        admin_email=current_user.email,
        action="delete_user",
        target_email=user_email,
        details=f"Deleted user and {len(user_forms)} form(s)",
    )

    return {"success": True, "message": f"User {user_email} and all related data deleted"}


# ═══════════════════════════════════════════════════════════════
# 7. BULK ROLE UPDATE
# ═══════════════════════════════════════════════════════════════

@router.post("/users/bulk-role", response_model=BulkActionResult)
def bulk_update_roles(
    data: BulkRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update roles for multiple users at once."""
    _require_admin(current_user)

    if data.role not in ("admin", "user"):
        raise HTTPException(400, detail="Role must be 'admin' or 'user'")

    # Exclude self from bulk update
    user_ids = [uid for uid in data.user_ids if uid != current_user.id]

    updated = (
        db.query(User)
        .filter(User.id.in_(user_ids))
        .update({User.role: data.role}, synchronize_session="fetch")
    )
    db.commit()

    _log_action(
        db,
        admin_email=current_user.email,
        action=f"bulk_role_change->{data.role}",
        details=f"Bulk updated {updated} users to role '{data.role}'",
    )

    return BulkActionResult(
        success=True,
        updated_count=updated,
        message=f"Updated {updated} user(s) to role '{data.role}'",
    )


# ═══════════════════════════════════════════════════════════════
# 8. ACTIVITY LOG
# ═══════════════════════════════════════════════════════════════

@router.get("/activity-log")
def get_activity_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return paginated admin activity log."""
    _require_admin(current_user)

    query = db.query(AdminActivityLog)
    total = query.count()

    logs = (
        query.order_by(AdminActivityLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "logs": [
            {
                "id": log.id,
                "admin_email": log.admin_email,
                "action": log.action,
                "target_user_email": log.target_user_email,
                "details": log.details,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs
        ],
    }


# ═══════════════════════════════════════════════════════════════
# 9. ALL FORMS (admin view)
# ═══════════════════════════════════════════════════════════════

@router.get("/forms")
def admin_list_forms(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all forms across all users (admin overview)."""
    _require_admin(current_user)

    query = db.query(Form)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (Form.title.ilike(pattern)) | (Form.created_by.ilike(pattern))
        )
    if status:
        query = query.filter(Form.status == status)

    total = query.count()
    forms = (
        query.order_by(Form.created_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "forms": [
            {
                "id": f.id,
                "title": f.title,
                "created_by": f.created_by,
                "status": f.status,
                "response_count": f.response_count or 0,
                "created_date": f.created_date.isoformat() if f.created_date else None,
            }
            for f in forms
        ],
    }


# ═══════════════════════════════════════════════════════════════
# 10. RECENT RESPONSES (admin view)
# ═══════════════════════════════════════════════════════════════

@router.get("/responses/recent")
def admin_recent_responses(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the most recent form responses across all forms."""
    _require_admin(current_user)

    responses = (
        db.query(FormResponse)
        .order_by(FormResponse.created_date.desc())
        .limit(limit)
        .all()
    )

    results = []
    for r in responses:
        form = db.query(Form).filter(Form.id == r.form_id).first()
        results.append({
            "id": r.id,
            "form_id": r.form_id,
            "form_title": form.title if form else "Unknown",
            "form_owner": form.created_by if form else "Unknown",
            "respondent_email": r.respondent_email,
            "respondent_name": r.respondent_name,
            "created_date": r.created_date.isoformat() if r.created_date else None,
            "answer_count": len(r.answers) if r.answers else 0,
        })

    return {"responses": results}
