import hashlib
from datetime import datetime, timedelta, timezone

from pymongo.database import Database

from app.repositories.user_repository import find_by_email
from app.security.password import verify_password

MAX_LOGIN_FAILURES = 8
LOCK_WINDOW = timedelta(minutes=15)


def _attempt_key(identifier: str, remote_ip: str) -> str:
    raw = f"{identifier.strip().lower()}|{remote_ip}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def authenticate(database: Database, role: str, identifier: str, password: str, remote_ip: str) -> dict | None:
    now = datetime.now(timezone.utc)
    attempt_id = _attempt_key(identifier, remote_ip)
    attempt = database.auth_attempts.find_one({"_id": attempt_id, "expires_at": {"$gt": now}})
    if attempt and attempt.get("failures", 0) >= MAX_LOGIN_FAILURES:
        return None

    normalized = identifier.strip().lower()
    if role == "student" and "@" not in normalized:
        student = database.students.find_one({"usn": identifier.strip().upper(), "active": {"$ne": False}})
        user = database.users.find_one({"_id": student["user_id"], "role": role}) if student else None
    else:
        user = find_by_email(database, normalized, role)

    valid = bool(user and user.get("is_active", True) and verify_password(password, user.get("password_hash")))
    if not valid:
        database.auth_attempts.update_one(
            {"_id": attempt_id},
            {
                "$inc": {"failures": 1},
                "$set": {"expires_at": now + LOCK_WINDOW},
            },
            upsert=True,
        )
        return None
    database.auth_attempts.delete_one({"_id": attempt_id})
    return user
