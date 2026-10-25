from bson import ObjectId
from pymongo.database import Database


def by_user_id(database: Database, user_id: ObjectId, *, active_only: bool = True) -> dict | None:
    query = {"user_id": user_id}
    if active_only:
        query["active"] = {"$ne": False}
    return database.teachers.find_one(query)


def assigned_subject_ids(database: Database, teacher_id: ObjectId) -> list[ObjectId]:
    return [row["subject_id"] for row in database.subject_assignments.find({"teacher_id": teacher_id, "active": {"$ne": False}})]
