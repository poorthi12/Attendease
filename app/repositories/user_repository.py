from bson import ObjectId
from pymongo.database import Database


def find_by_email(database: Database, email: str, role: str | None = None) -> dict | None:
    query = {"email": email.strip().lower()}
    if role:
        query["role"] = role
    return database.users.find_one(query)


def find_by_id(database: Database, user_id: ObjectId, *, active_only: bool = True) -> dict | None:
    query = {"_id": user_id}
    if active_only:
        query["is_active"] = True
    return database.users.find_one(query)
