from datetime import datetime, timezone

from bson import ObjectId


def subject_document(code: str, name: str, department: str, academic_year: str, semester: str) -> dict:
    return {"_id": ObjectId(), "code": code.strip().upper(), "name": name.strip(), "department": department.strip(), "academic_year": academic_year.strip(), "semester": semester.strip(), "active": True, "created_at": datetime.now(timezone.utc)}
