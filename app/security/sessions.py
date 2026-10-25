import secrets
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import Depends, HTTPException, Request, status
from pymongo.database import Database

from app.database import get_database


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, supplied: str | None) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The form expired. Refresh and try again.")


def get_current_user(request: Request, database: Database = Depends(get_database)) -> dict[str, Any]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in to continue.")
    try:
        user = database.users.find_one({"_id": ObjectId(user_id), "is_active": True})
    except Exception as exc:
        if isinstance(exc, ValueError):
            user = None
        else:
            raise HTTPException(status_code=503, detail="Attendance data is temporarily unavailable.") from exc
    if not user:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Sign in again.")
    user["id"] = str(user.pop("_id"))
    return user


def user_id(user: dict[str, Any]) -> ObjectId:
    return ObjectId(user["id"])
