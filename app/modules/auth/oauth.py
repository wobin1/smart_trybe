from dataclasses import dataclass

from fastapi import HTTPException
from google.auth.transport import requests
from google.oauth2 import id_token

from app.core.config import settings
from app.domain.enums import OAuthProvider


@dataclass(frozen=True)
class OAuthUserInfo:
    provider_user_id: str
    email: str
    full_name: str | None
    email_verified: bool


def verify_oauth_token(provider: OAuthProvider, token: str) -> OAuthUserInfo:
    if provider == OAuthProvider.GOOGLE:
        return _verify_google_id_token(token)
    raise HTTPException(status_code=400, detail=f"Unsupported OAuth provider: {provider.value}")


def _verify_google_id_token(token: str) -> OAuthUserInfo:
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    try:
        payload = id_token.verify_oauth2_token(token, requests.Request(), settings.google_client_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Google ID token") from exc

    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Google account has no email")

    return OAuthUserInfo(
        provider_user_id=str(payload["sub"]),
        email=email,
        full_name=payload.get("name"),
        email_verified=bool(payload.get("email_verified")),
    )
