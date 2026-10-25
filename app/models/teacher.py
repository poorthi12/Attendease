from datetime import datetime, timezone

from bson import ObjectId


def teacher_document(user_id: ObjectId, department: str) -> dict:
    return {"_id": ObjectId(), "user_id": user_id, "department": department.strip(), "active": True, "created_at": datetime.now(timezone.utc)}
