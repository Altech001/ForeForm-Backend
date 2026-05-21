#type: ignore

import base64
import datetime
import hashlib
import secrets
from urllib.parse import urlencode

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth.jwt import get_current_user
from config import settings
from db import get_db
from models.user import User
from models.user_integration import UserIntegration
from schemas.integration import IntegrationStatus, OAuthCallback

router = APIRouter(prefix="/api/integrations/twitter", tags=["twitter-integrations"])

PROVIDER = "twitter"


def _twitter_scopes() -> str:
    return settings.TWITTER_OAUTH_SCOPES.strip() or "tweet.read users.read offline.access"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _client_auth_header() -> str:
    raw = f"{settings.TWITTER_OAUTH_CLIENT_ID}:{settings.TWITTER_OAUTH_CLIENT_SECRET}"
    return "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _setup_required_status() -> IntegrationStatus:
    setup_required = not settings.TWITTER_OAUTH_CLIENT_ID or not settings.TWITTER_OAUTH_CLIENT_SECRET
    return IntegrationStatus(
        provider=PROVIDER,
        is_connected=False,
        scopes=_twitter_scopes(),
        setup_required=setup_required,
        message="Twitter OAuth is not configured on the server." if setup_required else None,
    )


@router.get("/auth-url")
def get_auth_url(
    redirect_uri: str = Query(None, description="Frontend redirect URI"),
    current_user: User = Depends(get_current_user),
):
    if not settings.TWITTER_OAUTH_CLIENT_ID or not settings.TWITTER_OAUTH_CLIENT_SECRET:
        raise HTTPException(503, detail="Twitter OAuth is not configured on the server.")

    callback_uri = redirect_uri or settings.TWITTER_OAUTH_REDIRECT_URI
    scopes = _twitter_scopes()
    code_verifier = secrets.token_urlsafe(64)
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.TWITTER_OAUTH_CLIENT_ID,
            "redirect_uri": callback_uri,
            "scope": scopes,
            "state": secrets.token_urlsafe(24),
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return {
        "auth_url": f"https://twitter.com/i/oauth2/authorize?{params}",
        "code_verifier": code_verifier,
        "redirect_uri": callback_uri,
        "scopes": scopes,
    }


@router.post("/callback", response_model=IntegrationStatus)
def oauth_callback(
    data: OAuthCallback,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not data.code_verifier:
        raise HTTPException(400, detail="Missing Twitter PKCE verifier. Please start the connection again.")
    if not settings.TWITTER_OAUTH_CLIENT_ID or not settings.TWITTER_OAUTH_CLIENT_SECRET:
        raise HTTPException(503, detail="Twitter OAuth is not configured on the server.")

    token_resp = http_requests.post(
        "https://api.twitter.com/2/oauth2/token",
        data={
            "code": data.code,
            "grant_type": "authorization_code",
            "client_id": settings.TWITTER_OAUTH_CLIENT_ID,
            "redirect_uri": data.redirect_uri or settings.TWITTER_OAUTH_REDIRECT_URI,
            "code_verifier": data.code_verifier,
        },
        headers={
            "Authorization": _client_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    if token_resp.status_code != 200:
        detail = token_resp.json().get("error_description", "Twitter token exchange failed")
        raise HTTPException(400, detail=detail)

    tokens = token_resp.json()
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    token_expiry = datetime.datetime.utcnow() + datetime.timedelta(seconds=tokens.get("expires_in", 7200))

    user_resp = http_requests.get(
        "https://api.twitter.com/2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"user.fields": "username,name,profile_image_url"},
    )
    if user_resp.status_code != 200:
        raise HTTPException(400, detail="Connected to Twitter, but failed to read account profile.")

    profile = user_resp.json().get("data", {})
    username = profile.get("username") or profile.get("name") or "Twitter account"
    connected_label = f"@{username}" if not username.startswith("@") else username

    existing = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == current_user.id, UserIntegration.provider == PROVIDER)
        .first()
    )

    if existing:
        existing.access_token = access_token
        existing.refresh_token = refresh_token or existing.refresh_token
        existing.token_expiry = token_expiry
        existing.scopes = _twitter_scopes()
        existing.connected_email = connected_label
        existing.is_active = True
        existing.updated_date = datetime.datetime.utcnow()
    else:
        db.add(
            UserIntegration(
                user_id=current_user.id,
                provider=PROVIDER,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expiry=token_expiry,
                scopes=_twitter_scopes(),
                connected_email=connected_label,
                is_active=True,
            )
        )

    db.commit()

    return IntegrationStatus(
        provider=PROVIDER,
        is_connected=True,
        connected_email=connected_label,
        connected_at=datetime.datetime.utcnow(),
        scopes=_twitter_scopes(),
    )


@router.get("/status", response_model=IntegrationStatus)
def get_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = (
        db.query(UserIntegration)
        .filter(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == PROVIDER,
            UserIntegration.is_active == True,
        )
        .first()
    )
    if not integ:
        return _setup_required_status()

    return IntegrationStatus(
        provider=PROVIDER,
        is_connected=True,
        connected_email=integ.connected_email,
        connected_at=integ.created_date,
        scopes=integ.scopes,
    )


@router.delete("/disconnect")
def disconnect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = (
        db.query(UserIntegration)
        .filter(UserIntegration.user_id == current_user.id, UserIntegration.provider == PROVIDER)
        .first()
    )
    if integ:
        db.delete(integ)
        db.commit()
    return {"status": "disconnected", "provider": PROVIDER}
