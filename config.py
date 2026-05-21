#type: ignore

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./formflow.db")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "changeme")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    FRONTEND_ORIGINS: str = os.getenv("FRONTEND_ORIGINS", "")
    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "beta@info.pitbox.fun")
    FROM_NAME: str = os.getenv("FROM_NAME", "ForeForm")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")
    MOE_ORCHESTRATOR_MODEL: str = os.getenv("MOE_ORCHESTRATOR_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
    MOE_SUBAGENT_MODEL: str = os.getenv("MOE_SUBAGENT_MODEL", "meta/llama-3.3-70b-instruct")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    GEMINI_LIVE_MODEL: str = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")

    # Cloudinary Integration
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")

    # Google OAuth2 for Drive / Sheets integrations
    GOOGLE_OAUTH_CLIENT_ID: str = os.getenv(
        "GOOGLE_OAUTH_CLIENT_ID",
        "",
    )
    GOOGLE_OAUTH_CLIENT_SECRET: str = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    GOOGLE_OAUTH_REDIRECT_URI: str = os.getenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://localhost:5173/integrations/google/callback",
    )
    TWITTER_OAUTH_CLIENT_ID: str = os.getenv("TWITTER_OAUTH_CLIENT_ID", "")
    TWITTER_OAUTH_CLIENT_SECRET: str = os.getenv("TWITTER_OAUTH_CLIENT_SECRET", "")
    TWITTER_OAUTH_REDIRECT_URI: str = os.getenv(
        "TWITTER_OAUTH_REDIRECT_URI",
        "http://localhost:5173/integrations/twitter/callback",
    )
    TWITTER_OAUTH_SCOPES: str = os.getenv(
        "TWITTER_OAUTH_SCOPES",
        "tweet.read users.read offline.access",
    )

    def cors_origins(self) -> list[str]:
        configured = [
            origin.strip()
            for origin in self.FRONTEND_ORIGINS.split(",")
            if origin.strip()
        ]
        defaults = [
            self.FRONTEND_ORIGIN,
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
            "https://api.pitbox.fun",
            "https://fore-form.vercel.app",
            "https://form.pitbox.fun",
            "https://pitbox.fun",
        ]
        return list(dict.fromkeys([*configured, *defaults]))

settings = Settings()
