from bson import ObjectId
from pymongo.database import Database


def teacher_can_manage(database: Database, teacher_id: ObjectId, subject_id: ObjectId) -> bool:
    return database.subject_assignments.find_one({"teacher_id": teacher_id, "subject_id": subject_id, "active": {"$ne": False}}) is not None


def enrolled_student_ids(database: Database, subject_id: ObjectId) -> set[str]:
    return {str(row["student_id"]) for row in database.enrollments.find({"subject_id": subject_id, "active": {"$ne": False}})}
