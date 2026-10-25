import logging
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from bson import ObjectId
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError
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


def _insert_records_with_transaction(database: Database, session_doc: dict, records: list[dict], audit: dict) -> None:
    client = database.client
    with client.start_session() as mongo_session:
        with mongo_session.start_transaction():
            database.attendance_sessions.insert_one(session_doc, session=mongo_session)
            if records:
                database.attendance_records.insert_many(records, ordered=True, session=mongo_session)
            database.audit_logs.insert_one(audit, session=mongo_session)


def finalize_attendance(
    database: Database,
    *,
    subject_id: ObjectId,
    teacher_id: ObjectId,
    class_date: date,
    statuses: dict[str, str],
    enrolled_student_ids: set[str],
) -> ObjectId:
    """Finalize one unique class date. Atlas transactions provide all-or-nothing writes.

    If the deployment does not support transactions, a pending session is used and every
    partial write is removed before an error is returned. A unique (subject, date) index
    prevents concurrent teachers from creating duplicate sessions.
    """
    if not statuses or set(statuses) != enrolled_student_ids:
        raise ValueError("Attendance must include every currently enrolled student exactly once.")
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
        else:
            raise RuntimeError("Attendance is currently being saved. Wait briefly, then try again.")
    sid = ObjectId()
    session_doc = {
        "_id": sid,
        "subject_id": subject_id,
        "teacher_id": teacher_id,
        "date": class_date.isoformat(),
        "status": "finalized",
        "student_count": len(statuses),
        "created_at": now,
    }
    records = [
        {
            "session_id": sid,
            "subject_id": subject_id,
            "teacher_id": teacher_id,
            "student_id": ObjectId(student_id),
            "date": class_date.isoformat(),
            "status": state,
            "created_at": now,
        }
        for student_id, state in statuses.items()
    ]
    audit = {
        "actor_id": teacher_id,
        "action": "attendance.finalized",
        "target_id": sid,
        "subject_id": subject_id,
        "date": class_date.isoformat(),
        "created_at": now,
    }

    try:
        _insert_records_with_transaction(database, session_doc, records, audit)
    except DuplicateKeyError as exc:
        raise ValueError("Attendance has already been recorded for this subject and date.") from exc
    except (OperationFailure, NotImplementedError) as exc:
        # Standalone MongoDB does not support transactions. The fallback is recoverable,
        # and reports failure unless both the session and all records are persisted.
        if isinstance(exc, OperationFailure) and exc.code not in {20, 303, 251} and "transaction" not in str(exc).lower():
            raise
        logger.warning("MongoDB transactions are unavailable; using attendance compensation cleanup.")
        try:
            fallback = {**session_doc, "status": "finalizing"}
            database.attendance_sessions.insert_one(fallback)
            if records:
                database.attendance_records.insert_many(records, ordered=True)
            database.audit_logs.insert_one(audit)
            updated = database.attendance_sessions.update_one(
                {"_id": sid, "status": "finalizing"}, {"$set": {"status": "finalized"}}
            )
            if updated.modified_count != 1:
                raise RuntimeError("Attendance session could not be finalized.")
        except DuplicateKeyError as duplicate:
            database.attendance_records.delete_many({"session_id": sid})
            database.attendance_sessions.delete_one({"_id": sid})
            database.audit_logs.delete_many({"target_id": sid})
            raise ValueError("Attendance has already been recorded for this subject and date.") from duplicate
        except Exception as fallback_error:
            database.attendance_records.delete_many({"session_id": sid})
            database.attendance_sessions.delete_one({"_id": sid})
            database.audit_logs.delete_many({"target_id": sid})
            raise RuntimeError("Attendance could not be saved. No partial session was retained.") from fallback_error
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
