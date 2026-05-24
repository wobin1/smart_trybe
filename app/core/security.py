import bcrypt
from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    digest = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())
    return digest.decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(*, subject: str, extra_claims: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode: dict = {"sub": subject, "exp": expire}
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def parse_user_id_from_payload(payload: dict) -> UUID:
    sub = payload.get("sub")
    if not sub:
        raise JWTError("missing subject")
    return UUID(str(sub))
