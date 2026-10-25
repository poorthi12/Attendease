from bson import ObjectId
from pymongo.database import Database


def by_user_id(database: Database, user_id: ObjectId, *, active_only: bool = True) -> dict | None:
    query = {"user_id": user_id}
    if active_only:
        query["active"] = {"$ne": False}
    return database.students.find_one(query)


def active_enrollments(database: Database, student_id: ObjectId) -> list[dict]:
    return list(database.enrollments.find({"student_id": student_id, "active": {"$ne": False}}))
