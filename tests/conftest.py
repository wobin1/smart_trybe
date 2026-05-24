"""Pytest configuration — runs before test module imports."""

import os

# Prefer explicit test DB URL when running integration tests.
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

os.environ.setdefault("JWT_SECRET_KEY", "pytest-jwt-secret-key-at-least-32-characters-long")
