from bson import ObjectId
from pymongo.database import Database


def is_active_subject(database: Database, subject_id: ObjectId) -> bool:
    return database.subjects.find_one({"_id": subject_id, "active": {"$ne": False}}) is not None


def is_enrolled(database: Database, student_id: ObjectId, subject_id: ObjectId) -> bool:
    return database.enrollments.find_one({"student_id": student_id, "subject_id": subject_id, "active": {"$ne": False}}) is not None
