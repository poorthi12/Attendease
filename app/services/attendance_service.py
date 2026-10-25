import logging
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from bson import ObjectId
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.database import Database

logger = logging.getLogger(__name__)
PENDING_SESSION_MAX_AGE = timedelta(minutes=15)

def attendance_percentage(present_count: int, applicable_sessions: int) -> float | None:
    if present_count < 0 or applicable_sessions < 0 or present_count > applicable_sessions:
        raise ValueError("Attendance counts are inconsistent.")
    if applicable_sessions == 0:
        return None
    return round(present_count * 100 / applicable_sessions, 1)


def attendance_summary(sessions: Iterable[dict]) -> dict[str, int | float | None]:
    total = present = 0
    for session in sessions:
        count = int(session.get("applicable_sessions", 0))
        attended = int(session.get("present_count", 0))
        if count < 0 or attended < 0 or attended > count:
            raise ValueError("Attendance counts are inconsistent.")
        total += count
        present += attended
    return {
        "classes": total,
        "present": present,
        "absent": total - present,
        "percentage": attendance_percentage(present, total),
    }


def finalize_attendance(
    database: Database,
    *,
    subject_id: ObjectId,
    teacher_id: ObjectId,
    class_date: date,
    statuses: dict[str, str],
    enrolled_student_ids: set[str],
) -> ObjectId:
    """Save marks incrementally for one unique subject/date session.

    Each student's record is an independent durable write, so a teacher can save a few
    marks, leave, and continue later. The session is finalized once every currently
    enrolled student has a record. The unique subject/date index keeps one session per
    class date.
    """
    if not statuses:
        raise ValueError(
            "Mark at least one student from the roster; every currently enrolled student can be saved over multiple submissions."
        )
    if not set(statuses).issubset(enrolled_student_ids):
        raise ValueError("Attendance includes a student who is not currently enrolled.")
    if any(value not in {"present", "absent"} for value in statuses.values()):
        raise ValueError("Attendance status is invalid.")
    now = datetime.now(timezone.utc)
    existing = database.attendance_sessions.find_one({"subject_id": subject_id, "date": class_date.isoformat()})
    if existing and existing.get("status") == "finalized":
        raise ValueError("Attendance has already been recorded for this subject and date.")
    if existing and existing.get("status") == "finalizing":
        created_at = existing.get("created_at")
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at and created_at < now - PENDING_SESSION_MAX_AGE:
            # A process may have exited mid-fallback. Finalizing sessions are never
            # visible as attendance, so remove their partial children before retrying.
            old_id = existing["_id"]
            database.attendance_records.delete_many({"session_id": old_id})
            database.audit_logs.delete_many({"target_id": old_id})
            database.attendance_sessions.delete_one({"_id": old_id, "status": "finalizing"})
            existing = None
        else:
            raise RuntimeError("Attendance is currently being saved. Wait briefly, then try again.")
    try:
        sid = existing["_id"] if existing else ObjectId()
        if not existing:
            session_doc = {
                "_id": sid,
                "subject_id": subject_id,
                "teacher_id": teacher_id,
                "date": class_date.isoformat(),
                "status": "in_progress",
                "student_count": 0,
                "expected_count": len(enrolled_student_ids),
                "created_at": now,
            }
            try:
                database.attendance_sessions.insert_one(session_doc)
            except DuplicateKeyError:
                # A concurrent save may have created the unique subject/date session.
                existing = database.attendance_sessions.find_one(
                    {"subject_id": subject_id, "date": class_date.isoformat()}
                )
                if not existing:
                    raise
                sid = existing["_id"]
                if existing.get("status") == "finalized":
                    raise ValueError("Attendance has already been recorded for this subject and date.")
                if existing.get("status") == "finalizing":
                    raise RuntimeError("Attendance is currently being saved. Wait briefly, then try again.")

        for student_id, state in statuses.items():
            record_filter = {"session_id": sid, "student_id": ObjectId(student_id)}
            record_values = {
                "subject_id": subject_id,
                "teacher_id": teacher_id,
                "date": class_date.isoformat(),
                "status": state,
                "updated_at": now,
            }
            try:
                database.attendance_records.update_one(
                    record_filter,
                    {"$set": record_values, "$setOnInsert": {"created_at": now}},
                    upsert=True,
                )
            except DuplicateKeyError:
                # Another save inserted the same student's record between the upsert
                # lookup and insert. Update that record and keep the save idempotent.
                database.attendance_records.update_one(record_filter, {"$set": record_values})

        marked_count = database.attendance_records.count_documents({"session_id": sid})
        marked_ids = {
            str(row["student_id"])
            for row in database.attendance_records.find(
                {"session_id": sid, "student_id": {"$in": [ObjectId(student_id) for student_id in enrolled_student_ids]}},
                {"student_id": 1},
            )
        }
        is_complete = enrolled_student_ids.issubset(marked_ids)
        database.attendance_sessions.update_one(
            {"_id": sid, "status": {"$ne": "finalized"}},
            {
                "$set": {
                    "status": "finalized" if is_complete else "in_progress",
                    "student_count": marked_count,
                    "expected_count": len(enrolled_student_ids),
                    "updated_at": now,
                }
            },
        )
        try:
            database.audit_logs.insert_one(
                {
                    "actor_id": teacher_id,
                    "action": "attendance.finalized" if is_complete else "attendance.saved",
                    "target_id": sid,
                    "subject_id": subject_id,
                    "date": class_date.isoformat(),
                    "student_ids": [ObjectId(student_id) for student_id in statuses],
                    "created_at": now,
                }
            )
        except PyMongoError as audit_error:
            # Attendance records are already durable. A logging outage must not make
            # the teacher repeat a save that has actually succeeded.
            logger.warning("Attendance was saved but its audit event failed (%s).", type(audit_error).__name__)
    except PyMongoError as exc:
        raise RuntimeError("Attendance could not be saved. Please try again.") from exc
    return sid


def records_for_student(database: Database, student_id: ObjectId, subject_ids: list[ObjectId]) -> list[dict]:
    if not subject_ids:
        return []
    return list(
        database.attendance_records.find({"student_id": student_id, "subject_id": {"$in": subject_ids}})
        .sort([("date", ASCENDING), ("created_at", ASCENDING)])
    )
