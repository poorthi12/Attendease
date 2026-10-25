from bson import ObjectId
from pymongo import DESCENDING
from pymongo.database import Database


def records_for_student(database: Database, student_id: ObjectId, subject_ids: list[ObjectId] | None = None) -> list[dict]:
    query = {"student_id": student_id}
    if subject_ids is not None:
        if not subject_ids:
            return []
        query["subject_id"] = {"$in": subject_ids}
    return list(database.attendance_records.find(query).sort("date", DESCENDING))


def finalized_sessions(database: Database, subject_ids: list[ObjectId]) -> list[dict]:
    if not subject_ids:
        return []
    return list(database.attendance_sessions.find({"subject_id": {"$in": subject_ids}, "status": "finalized"}).sort("date", DESCENDING))
