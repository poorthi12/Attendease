from datetime import datetime, timezone
from typing import Literal

from bson import ObjectId

UserRole = Literal["student", "teacher", "admin"]


def user_document(name: str, email: str, role: UserRole, password_hash: str) -> dict:
    return {
        "_id": ObjectId(),
        "name": name.strip(),
        "email": email.strip().lower(),
        "role": role,
        "password_hash": password_hash,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
