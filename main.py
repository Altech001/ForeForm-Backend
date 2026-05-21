#type: ignore

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from db import engine, Base
from migrations import ensure_quiz_columns

# Import all models so SQLAlchemy registers them before create_all
from models import User, Form, FormResponse, FormShare, Task, TaskActivity, AgentSession, ApiKey, UserIntegration, AdminActivityLog  # noqa: F401

# Import routers
from routers.auth import router as auth_router
from routers.forms import router as forms_router
from routers.responses import router as responses_router
from routers.upload import router as upload_router
from routers.shares import router as shares_router
from routers.ai import router as ai_router
from routers.tasks import router as tasks_router
from routers.files_better import router as documents_router
from routers.sect_form import router as sections_router
from routers.foreform_agents import router as agent_router
from routers.agentic_fill import router as agentic_fill_router
from routers.google_integrations import router as google_integrations_router
from routers.admin import router as admin_router
from routers.google_sheet_upload import router as sheets_router
from routers.drive_explorer import router as drive_explorer_router
from routers.email import router as email_router
from routers.fore_models import router as models_router

# ── Create tables ────────────────────────────────────────────
Base.metadata.create_all(bind=engine)
ensure_quiz_columns(engine)

# ── App ──────────────────────────────────────────────────────
app = FastAPI(
    title="FormFore API",
    description="Research-grade form builder backend — forms, responses, sharing, file uploads, and AI extraction.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([
        settings.FRONTEND_ORIGIN,
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "https://foreform.vercel.app",
        "https://fore-form.vercel.app",
        "https://form.pitbox.fun",
        "https://pitbox.fun",
    ])),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ────────────────────────────────────────
app.include_router(auth_router)
app.include_router(forms_router)
app.include_router(responses_router)
app.include_router(upload_router)
app.include_router(shares_router)
app.include_router(ai_router)
app.include_router(tasks_router)
app.include_router(documents_router)
app.include_router(sections_router)
app.include_router(agent_router)
app.include_router(agentic_fill_router)
app.include_router(google_integrations_router)
app.include_router(admin_router)
app.include_router(sheets_router)
app.include_router(drive_explorer_router)
app.include_router(email_router)
app.include_router(models_router, prefix="/api")


# ── Health check ─────────────────────────────────────────────
@app.get("/", tags=["health"])
def root():
    return {
        "app": "FormFlow API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
