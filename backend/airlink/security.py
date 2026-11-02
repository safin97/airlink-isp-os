import hashlib
import secrets
from datetime import timedelta, timezone
import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .config import settings
from .section_access import enforce_request, require_any, role_policy
from .db import get_db
from .models import User, LoginSession, RefreshToken, now

hasher = PasswordHasher(type=Type.ID, time_cost=3, memory_cost=65536, parallelism=2)
bearer = HTTPBearer(auto_error=False)
# Equal-cost verification even when username is unknown.
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def password_valid(value):
    if not 14 <= len(value) <= 128 or len(set(value)) < 8:
        raise ValueError("Use 14–128 characters with at least 8 distinct characters")
    if value.lower() in {"password123456!", "airlinkisp2026!"}:
        raise ValueError("Choose a less predictable password")
    return value


def verify_password(value, hashed):
    try:
        return hasher.verify(hashed, value)
    except (VerificationError, InvalidHashError):
        return False


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def access_token(user, session):
    return jwt.encode({"sub": user.id, "sid": session.id, "iat": now(),
                       "exp": now() + timedelta(seconds=settings.access_seconds),
                       "iss": "airlink", "aud": "airlink-dashboard"}, settings.secret, algorithm="HS256")


def issue_refresh(db, session):
    value = secrets.token_urlsafe(48)
    db.add(RefreshToken(digest=digest(value), session_id=session.id))
    return value


def resolve_user(token, db):
    try:
        claims = jwt.decode(token, settings.secret, algorithms=["HS256"], audience="airlink-dashboard", issuer="airlink",
                            options={"require": ["sub", "sid", "iat", "exp"]})
        session = db.get(LoginSession, claims["sid"])
        user = db.get(User, claims["sub"])
        if not session or session.user_id != claims["sub"] or session.revoked or aware(session.expires_at) <= now() or not user or not user.active:
            raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "Session expired; sign in again")


def current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(get_db)):
    if not credentials:
        raise HTTPException(401, "Sign in required")
    user = resolve_user(credentials.credentials, db)
    enforce_request(user, request.method, request.url.path)
    return user


def owner(user=Depends(current_user)):
    if user.role != "owner":
        raise HTTPException(403, "Owner access required")
    return user


def delegated_section(section):
    def access(user=Depends(current_user)):
        if user.role == 'owner':
            return user
        if user.role != 'manager' and role_policy(user) is None:
            raise HTTPException(403, 'Owner or authorized manager access required')
        require_any(user, (section,))
        return user
    return access


settings_access = delegated_section('settings')
updates_access = delegated_section('software_updates')


def cipher():
    return Fernet(settings.encryption_key.encode())
