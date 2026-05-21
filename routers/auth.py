from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from db import get_db
from models.user import User
from schemas.user import UserRegister, UserLogin, Token, UserOut, GoogleLoginParams
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from auth.jwt import hash_password, verify_password, create_access_token, get_current_user
from config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: UserRegister, db: Session = Depends(get_db)):
    """Create a new user account."""
    email = normalize_email(str(data.email))
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=email,
        full_name=data.full_name.strip(),
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    """Authenticate and return a JWT access token."""
    email = normalize_email(str(data.email))
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/google", response_model=Token)
def google_login(data: GoogleLoginParams, db: Session = Depends(get_db)):
    """Authenticate via Google and return a JWT access token."""
    try:
        idinfo = id_token.verify_oauth2_token(data.token, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID)
        email = normalize_email(idinfo.get('email', ''))
        name = idinfo.get('name', 'Google User')
        if not email:
            raise ValueError("No email in token")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user:
        user = User(
            email=email,
            full_name=name,
            hashed_password=hash_password("google_oauth_fallback_" + email),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return current_user
