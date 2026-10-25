from datetime import date, datetime, timezone

from bson import ObjectId


def attendance_session_document(subject_id: ObjectId, teacher_id: ObjectId, class_date: date, count: int) -> dict:
    return {"_id": ObjectId(), "subject_id": subject_id, "teacher_id": teacher_id, "date": class_date.isoformat(), "status": "finalized", "student_count": count, "created_at": datetime.now(timezone.utc)}


def attendance_record_document(session_id: ObjectId, subject_id: ObjectId, teacher_id: ObjectId, student_id: ObjectId, class_date: date, status: str) -> dict:
    if status not in {"present", "absent"}:
        raise ValueError("Attendance status must be present or absent.")
    return {"session_id": session_id, "subject_id": subject_id, "teacher_id": teacher_id, "student_id": student_id, "date": class_date.isoformat(), "status": status, "created_at": datetime.now(timezone.utc)}
