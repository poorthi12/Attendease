from bson import ObjectId
from pymongo.database import Database


def active_by_ids(database: Database, subject_ids: list[ObjectId]) -> list[dict]:
    if not subject_ids:
        return []
    return list(database.subjects.find({"_id": {"$in": subject_ids}, "active": {"$ne": False}}))


def assigned_to(database: Database, teacher_id: ObjectId, subject_id: ObjectId) -> bool:
    return database.subject_assignments.find_one({"teacher_id": teacher_id, "subject_id": subject_id, "active": {"$ne": False}}) is not None
