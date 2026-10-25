from datetime import datetime, timezone

from bson import ObjectId


def student_document(user_id: ObjectId, usn: str, branch: str, department: str, academic_year: str) -> dict:
    return {"_id": ObjectId(), "user_id": user_id, "usn": usn.strip().upper(), "branch": branch.strip(), "department": department.strip(), "academic_year": academic_year.strip(), "active": True, "created_at": datetime.now(timezone.utc)}
