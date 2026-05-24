"""Unit tests for password hashing and JWT helpers (no database required)."""

from uuid import uuid4

from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    secret = "correcthorsebatterystaple99"
    hashed = hash_password(secret)
    assert verify_password(secret, hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_subject_roundtrip():
    uid = str(uuid4())
    token = create_access_token(subject=uid)
    payload = decode_token(token)
    assert payload["sub"] == uid
