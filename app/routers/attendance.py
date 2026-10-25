from datetime import date

from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pymongo.database import Database
from starlette.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from app.database import get_database
from app.routers.teacher import require_assigned
from app.schemas.attendance import AttendanceSubmission
from app.security.permissions import require_role
from app.security.sessions import verify_csrf
from app.services.attendance_service import finalize_attendance
from app.utils.responses import render

router = APIRouter(tags=["attendance"])
teacher_only = Depends(require_role("teacher"))


def _roster(database: Database, subject_id: str) -> list[dict]:
    enrollments = list(database.enrollments.find({"subject_id": ObjectId(subject_id), "active": {"$ne": False}}))
    ids = [row["student_id"] for row in enrollments]
    students = list(database.students.find({"_id": {"$in": ids}, "active": {"$ne": False}})) if ids else []
    roster = []
    for student in students:
        user = database.users.find_one({"_id": student["user_id"], "is_active": True})
        if user:
            roster.append(
                {
                    "id": str(student["_id"]),
                    "name": user.get("name", ""),
                    "usn": student.get("usn", ""),
                    "branch": student.get("branch", ""),
                    "department": student.get("department", ""),
                    "academic_year": student.get("academic_year", ""),
                    "semester": student.get("semester", ""),
                }
            )
    return sorted(roster, key=lambda row: row["name"].casefold())


def _persist_attendance(database: Database, user: dict, subject_id: str, form: dict):
    subject = require_assigned(database, user, subject_id)
    roster = _roster(database, subject_id)
    expected_fields = {f"status_{student['id']}" for student in roster}
    submitted_fields = {key for key in form if key.startswith("status_")}
    if submitted_fields != expected_fields:
        raise ValueError("The submitted roster changed. Reload the form and review the full class.")
    statuses = {student["id"]: str(form.get(f"status_{student['id']}", "")) for student in roster}
    submission = AttendanceSubmission.model_validate({"class_date": form.get("class_date"), "statuses": statuses})
    session_id = finalize_attendance(
        database,
        subject_id=ObjectId(subject_id),
        teacher_id=subject["teacher_id"],
        class_date=submission.class_date,
        statuses=submission.statuses,
        enrolled_student_ids={student["id"] for student in roster},
    )
    return subject, roster, session_id


@router.get("/teacher/subjects/{subject_id}/attendance/new")
def attendance_form(subject_id: str, request: Request, database: Database = Depends(get_database), user: dict = teacher_only):
    subject = require_assigned(database, user, subject_id)
    roster = _roster(database, subject_id)
    return render(request, "teacher/mark_attendance.html", title="Mark attendance", subject=subject, students=roster, today=date.today().isoformat())


@router.post("/teacher/subjects/{subject_id}/attendance/new")
async def submit_attendance(subject_id: str, request: Request, database: Database = Depends(get_database), user: dict = teacher_only):
    form = await request.form()
    verify_csrf(request, str(form.get("csrf", "")))
    try:
        subject, roster, session_id = await run_in_threadpool(_persist_attendance, database, user, subject_id, dict(form))
    except ValueError as exc:
        subject = await run_in_threadpool(require_assigned, database, user, subject_id)
        roster = await run_in_threadpool(_roster, database, subject_id)
        request.session["flash"] = {"kind": "error", "message": str(exc)}
        return render(request, "teacher/mark_attendance.html", status_code=400, title="Mark attendance", subject=subject, students=roster, today=date.today().isoformat())
    except RuntimeError as exc:
        subject = await run_in_threadpool(require_assigned, database, user, subject_id)
        roster = await run_in_threadpool(_roster, database, subject_id)
        request.session["flash"] = {"kind": "error", "message": str(exc)}
        return render(request, "teacher/mark_attendance.html", status_code=503, title="Mark attendance", subject=subject, students=roster, today=date.today().isoformat())
    request.session["flash"] = {"kind": "success", "message": "Attendance was saved for the full class."}
    return RedirectResponse("/teacher/attendance-history?subject_id=" + subject_id, status_code=303)
