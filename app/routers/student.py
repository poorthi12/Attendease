from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pymongo import DESCENDING
from pymongo.database import Database

from app.database import get_database
from app.security.permissions import require_role
from app.repositories.attendance_repository import records_for_student
from app.repositories.student_repository import active_enrollments, by_user_id
from app.services.analytics_service import summarize_student_records
from app.services.student_service import absent_dates as sorted_absent_dates
from app.utils.dates import valid_iso_date
from app.utils.responses import render

router = APIRouter(prefix="/student", tags=["student"])
student_only = Depends(require_role("student"))


def _student_context(database: Database, user: dict) -> tuple[dict, list[dict], list[dict]]:
    student = by_user_id(database, ObjectId(user["id"]))
    if not student:
        return {}, [], []
    enrollments = active_enrollments(database, student["_id"])
    subject_ids = [row["subject_id"] for row in enrollments]
    subjects = list(database.subjects.find({"_id": {"$in": subject_ids}, "active": {"$ne": False}})) if subject_ids else []
    records = [row for row in records_for_student(database, student["_id"], subject_ids) if row.get("status") in {"present", "absent"}]
    stats = summarize_student_records(records, [str(subject_id) for subject_id in subject_ids])
    account = database.users.find_one({"_id": student["user_id"]}) or {}
    student["name"] = account.get("name", "")
    student["email"] = account.get("email", "")
    for subject in subjects:
        subject["id"] = str(subject.pop("_id"))
        subject["stats"] = stats["subjects"].get(subject["id"], {"classes": 0, "present": 0, "absent": 0, "percentage": None})
        assignment = database.subject_assignments.find_one({"subject_id": ObjectId(subject["id"]), "active": {"$ne": False}})
        teacher = database.teachers.find_one({"_id": assignment["teacher_id"]}) if assignment else None
        if teacher:
            teacher_user = database.users.find_one({"_id": teacher["user_id"]})
            subject["teacher_name"] = teacher_user.get("name", "") if teacher_user else "Unassigned"
        else:
            subject["teacher_name"] = "Unassigned"
    student["id"] = str(student.pop("_id"))
    for record in records:
        record["id"] = str(record.pop("_id"))
        subject = next((item for item in subjects if item["id"] == str(record["subject_id"])), None)
        record["subject"] = subject["name"] if subject else "Archived subject"
        record["subject_code"] = subject["code"] if subject else "—"
        record["teacher_name"] = subject["teacher_name"] if subject else "—"
    return student, subjects, records


@router.get("")
def dashboard(request: Request, database: Database = Depends(get_database), user: dict = student_only):
    student, subjects, records = _student_context(database, user)
    stats = summarize_student_records(records, [item["id"] for item in subjects]) if student else {"overall": {"classes": 0, "present": 0, "absent": 0, "percentage": None}, "subjects": {}}
    recent = records[:6]
    chart = {"labels": [item["name"] for item in subjects], "values": [item["stats"]["percentage"] or 0 for item in subjects]}
    return render(request, "student/dashboard.html", title="Overview", student=student, subjects=subjects, recent=recent, stats=stats["overall"], chart=chart)


@router.get("/profile")
def profile(request: Request, database: Database = Depends(get_database), user: dict = student_only):
    student, _, _ = _student_context(database, user)
    return render(request, "student/profile.html", title="My profile", student=student)


@router.get("/subjects")
def subjects_page(request: Request, q: str = "", database: Database = Depends(get_database), user: dict = student_only):
    student, subjects, _ = _student_context(database, user)
    query = q.strip().casefold()
    if query:
        subjects = [item for item in subjects if query in item.get("name", "").casefold() or query in item.get("code", "").casefold()]
    return render(request, "student/subjects.html", title="My subjects", student=student, subjects=subjects, query=q)


@router.get("/attendance")
def attendance_page(
    request: Request,
    subject: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    database: Database = Depends(get_database),
    user: dict = student_only,
):
    student, subjects, records = _student_context(database, user)
    valid_subjects = {item["id"] for item in subjects}
    if subject in valid_subjects:
        records = [row for row in records if str(row["subject_id"]) == subject]
    if status in {"present", "absent"}:
        records = [row for row in records if row["status"] == status]
    start, end = valid_iso_date(date_from), valid_iso_date(date_to)
    if start:
        records = [row for row in records if row["date"] >= start]
    if end:
        records = [row for row in records if row["date"] <= end]
    return render(request, "student/attendance.html", title="Attendance", student=student, subjects=subjects, records=records, filters={"subject": subject, "status": status, "date_from": start or "", "date_to": end or ""})


@router.get("/absent-dates")
def absent_dates(
    request: Request,
    subject: str = "",
    date_from: str = "",
    date_to: str = "",
    database: Database = Depends(get_database),
    user: dict = student_only,
):
    student, subjects, records = _student_context(database, user)
    valid_subjects = {item["id"] for item in subjects}
    absences = [row for row in records if row["status"] == "absent"]
    if subject in valid_subjects:
        absences = [row for row in absences if str(row["subject_id"]) == subject]
    start, end = valid_iso_date(date_from), valid_iso_date(date_to)
    if start:
        absences = [row for row in absences if row["date"] >= start]
    if end:
        absences = [row for row in absences if row["date"] <= end]
    absences = sorted_absent_dates(absences)
    return render(request, "student/absent_dates.html", title="Absent dates", student=student, subjects=subjects, records=absences, filters={"subject": subject, "date_from": start or "", "date_to": end or ""})
