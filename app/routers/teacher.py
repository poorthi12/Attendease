from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pymongo import DESCENDING
from pymongo.database import Database

from app.database import get_database
from app.repositories.subject_repository import active_by_ids, assigned_to
from app.repositories.teacher_repository import assigned_subject_ids, by_user_id
from app.security.permissions import require_role
from app.services.analytics_service import summarize_teacher_records
from app.services.attendance_service import attendance_percentage
from app.utils.responses import render

router = APIRouter(prefix="/teacher", tags=["teacher"])
teacher_only = Depends(require_role("teacher"))


def assigned_subjects(database: Database, user: dict) -> list[dict]:
    teacher = by_user_id(database, ObjectId(user["id"]))
    if not teacher:
        return []
    ids = assigned_subject_ids(database, teacher["_id"])
    subjects = active_by_ids(database, ids)
    for subject in subjects:
        subject["id"] = str(subject.pop("_id"))
        subject["enrollment_count"] = database.enrollments.count_documents({"subject_id": ObjectId(subject["id"]), "active": {"$ne": False}})
        subject["session_count"] = database.attendance_sessions.count_documents({"subject_id": ObjectId(subject["id"]), "status": "finalized"})
    return subjects


def require_assigned(database: Database, user: dict, subject_id: str) -> dict:
    try:
        subject_oid = ObjectId(subject_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Subject not found.") from exc
    teacher = by_user_id(database, ObjectId(user["id"]))
    subject = database.subjects.find_one({"_id": subject_oid, "active": {"$ne": False}}) if teacher and assigned_to(database, teacher["_id"], subject_oid) else None
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found.")
    subject["id"] = str(subject.pop("_id"))
    subject["teacher_id"] = teacher["_id"]
    return subject


def _subject_stats(database: Database, subject: dict) -> dict:
    subject_id = ObjectId(subject["id"])
    records = list(database.attendance_records.find({"subject_id": subject_id}))
    present = sum(record.get("status") == "present" for record in records)
    absent = sum(record.get("status") == "absent" for record in records)
    applicable = present + absent
    enrolled = database.enrollments.count_documents({"subject_id": subject_id, "active": {"$ne": False}})
    sessions = database.attendance_sessions.count_documents({"subject_id": subject_id, "status": "finalized"})
    return {"present": present, "absent": absent, "sessions": sessions, "enrolled": enrolled, "percentage": attendance_percentage(present, applicable)}


@router.get("")
def dashboard(request: Request, database: Database = Depends(get_database), user: dict = teacher_only):
    subjects = assigned_subjects(database, user)
    for subject in subjects:
        subject["stats"] = _subject_stats(database, subject)
    all_records = list(database.attendance_records.find({"subject_id": {"$in": [ObjectId(item["id"]) for item in subjects]}}).sort("date", DESCENDING)) if subjects else []
    stats = summarize_teacher_records(all_records)
    recent_sessions = list(database.attendance_sessions.find({"subject_id": {"$in": [ObjectId(item["id"]) for item in subjects]}, "status": "finalized"}).sort("date", DESCENDING).limit(5)) if subjects else []
    for session in recent_sessions:
        subject = next((item for item in subjects if item["id"] == str(session["subject_id"])), None)
        session["subject_name"] = subject["name"] if subject else "Subject"
    return render(request, "teacher/dashboard.html", title="Overview", subjects=subjects, stats=stats, recent_sessions=recent_sessions)


@router.get("/subjects")
def subjects_page(request: Request, database: Database = Depends(get_database), user: dict = teacher_only):
    subjects = assigned_subjects(database, user)
    for subject in subjects:
        subject["stats"] = _subject_stats(database, subject)
    return render(request, "teacher/subjects.html", title="Assigned subjects", subjects=subjects)


@router.get("/subjects/{subject_id}/students")
def student_list(subject_id: str, request: Request, q: str = "", database: Database = Depends(get_database), user: dict = teacher_only):
    subject = require_assigned(database, user, subject_id)
    enrollments = list(database.enrollments.find({"subject_id": ObjectId(subject_id), "active": {"$ne": False}}))
    student_ids = [row["student_id"] for row in enrollments]
    students = list(database.students.find({"_id": {"$in": student_ids}, "active": {"$ne": False}})) if student_ids else []
    sessions = database.attendance_sessions.count_documents({"subject_id": ObjectId(subject_id), "status": "finalized"})
    query = q.strip().casefold()
    rows = []
    for student in students:
        user_doc = database.users.find_one({"_id": student["user_id"]})
        records = list(database.attendance_records.find({"subject_id": ObjectId(subject_id), "student_id": student["_id"]}))
        present = sum(row.get("status") == "present" for row in records)
        applicable = sum(row.get("status") in {"present", "absent"} for row in records)
        rows.append({**student, "id": str(student["_id"]), "name": user_doc.get("name", "") if user_doc else "Unknown", "present": present, "absent": applicable - present, "percentage": attendance_percentage(present, applicable)})
    if query:
        rows = [row for row in rows if query in row.get("name", "").casefold() or query in row.get("usn", "").casefold()]
    return render(request, "teacher/student_list.html", title="Enrolled students", subject=subject, students=rows, query=q)


@router.get("/attendance-history")
def attendance_history(request: Request, subject_id: str = "", database: Database = Depends(get_database), user: dict = teacher_only):
    subjects = assigned_subjects(database, user)
    allowed = {item["id"] for item in subjects}
    if subject_id and subject_id not in allowed:
        raise HTTPException(status_code=404, detail="Subject not found.")
    query = {"subject_id": ObjectId(subject_id)} if subject_id else {"subject_id": {"$in": [ObjectId(item["id"]) for item in subjects]}}
    sessions = list(database.attendance_sessions.find({**query, "status": "finalized"}).sort("date", DESCENDING).limit(200)) if subjects else []
    for session in sessions:
        subject = next((item for item in subjects if item["id"] == str(session["subject_id"])), None)
        rows = list(database.attendance_records.find({"session_id": session["_id"]}))
        session["id"] = str(session.pop("_id"))
        session["subject_name"] = subject["name"] if subject else "Subject"
        session["present_count"] = sum(row.get("status") == "present" for row in rows)
        session["absent_count"] = sum(row.get("status") == "absent" for row in rows)
    return render(request, "teacher/attendance_history.html", title="Attendance history", subjects=subjects, sessions=sessions, selected_subject=subject_id)


@router.get("/analytics")
def analytics(request: Request, database: Database = Depends(get_database), user: dict = teacher_only):
    subjects = assigned_subjects(database, user)
    subject_ids = [ObjectId(item["id"]) for item in subjects]
    records = list(database.attendance_records.find({"subject_id": {"$in": subject_ids}})) if subject_ids else []
    stats = summarize_teacher_records(records)
    subject_labels = []
    subject_values = []
    for subject in subjects:
        item_records = [row for row in records if str(row["subject_id"]) == subject["id"]]
        present = sum(row.get("status") == "present" for row in item_records)
        subject_labels.append(subject["code"])
        subject_values.append(round(present * 100 / len(item_records), 1) if item_records else 0)
    return render(request, "teacher/analytics.html", title="Analytics", subjects=subjects, stats=stats, chart={"labels": subject_labels, "values": subject_values, "trend_labels": list(stats["by_date"]), "present": [row["present"] for row in stats["by_date"].values()], "absent": [row["absent"] for row in stats["by_date"].values()], "present_total": stats["present"], "absent_total": stats["absent"]})
