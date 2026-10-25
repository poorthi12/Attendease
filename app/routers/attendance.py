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


def _form_date(value: str | None) -> date:
    try:
        selected = date.fromisoformat(value) if value else date.today()
    except ValueError:
        return date.today()
    return selected if selected <= date.today() else date.today()


def _saved_statuses(database: Database, subject_id: str, class_date: date) -> tuple[dict[str, str], bool]:
    session = database.attendance_sessions.find_one(
        {"subject_id": ObjectId(subject_id), "date": class_date.isoformat()}
    )
    if not session or session.get("status") not in {"in_progress", "finalized"}:
        return {}, False
    records = database.attendance_records.find({"session_id": session["_id"]})
    statuses = {str(record["student_id"]): record["status"] for record in records}
    return statuses, session.get("status") == "finalized"


def _marked_student_count(database: Database, session_id: ObjectId, roster: list[dict]) -> int:
    return database.attendance_records.count_documents(
        {
            "session_id": session_id,
            "student_id": {"$in": [ObjectId(student["id"]) for student in roster]},
        }
    )


def _attendance_page(
    request: Request,
    database: Database,
    subject: dict,
    roster: list[dict],
    class_date: date,
    *,
    status_code: int = 200,
    submitted: dict[str, str] | None = None,
):
    saved, complete = _saved_statuses(database, subject["id"], class_date)
    visible_statuses = {**saved, **{key: value for key, value in (submitted or {}).items() if value}}
    for student in roster:
        student["attendance_status"] = visible_statuses.get(student["id"], "")
        student["has_saved_status"] = student["id"] in saved
    marked_count = sum(student["id"] in saved for student in roster)
    return render(
        request,
        "teacher/mark_attendance.html",
        status_code=status_code,
        title="Mark attendance",
        subject=subject,
        students=roster,
        today=date.today().isoformat(),
        class_date=class_date.isoformat(),
        marked_count=marked_count,
        complete=complete,
    )


def _persist_attendance(database: Database, user: dict, subject_id: str, form: dict):
    subject = require_assigned(database, user, subject_id)
    roster = _roster(database, subject_id)
    expected_fields = {f"status_{student['id']}" for student in roster}
    submitted_fields = {key for key in form if key.startswith("status_")}
    if not submitted_fields.issubset(expected_fields):
        raise ValueError("The submitted roster changed. Reload the form and review the class.")
    statuses = {}
    submitted_for_page = {}
    for student in roster:
        student_id = student["id"]
        value = str(form.get(f"status_{student_id}", ""))
        if value not in {"", "present", "absent"}:
            raise ValueError("Choose present or absent for each student you mark.")
        submitted_for_page[student_id] = value
        if value:
            statuses[student_id] = value
    if not statuses:
        raise ValueError("Mark at least one student before saving attendance.")
    submission = AttendanceSubmission.model_validate({"class_date": form.get("class_date"), "statuses": statuses})
    session_id = finalize_attendance(
        database,
        subject_id=ObjectId(subject_id),
        teacher_id=subject["teacher_id"],
        class_date=submission.class_date,
        statuses=submission.statuses,
        enrolled_student_ids={student["id"] for student in roster},
    )
    return subject, roster, session_id, submission.class_date, submitted_for_page


@router.get("/teacher/subjects/{subject_id}/attendance/new")
def attendance_form(
    subject_id: str,
    request: Request,
    class_date: str = "",
    database: Database = Depends(get_database),
    user: dict = teacher_only,
):
    subject = require_assigned(database, user, subject_id)
    roster = _roster(database, subject_id)
    return _attendance_page(request, database, subject, roster, _form_date(class_date))


@router.post("/teacher/subjects/{subject_id}/attendance/new")
async def submit_attendance(subject_id: str, request: Request, database: Database = Depends(get_database), user: dict = teacher_only):
    form = await request.form()
    verify_csrf(request, str(form.get("csrf", "")))
    selected_date = _form_date(str(form.get("class_date", "")))
    submitted_statuses = {
        key.removeprefix("status_"): str(value)
        for key, value in form.items()
        if key.startswith("status_") and str(value) in {"", "present", "absent"}
    }
    try:
        subject, roster, session_id, selected_date, submitted_statuses = await run_in_threadpool(
            _persist_attendance, database, user, subject_id, dict(form)
        )
    except ValueError as exc:
        subject = await run_in_threadpool(require_assigned, database, user, subject_id)
        roster = await run_in_threadpool(_roster, database, subject_id)
        request.session["flash"] = {"kind": "error", "message": str(exc)}
        return _attendance_page(
            request,
            database,
            subject,
            roster,
            selected_date,
            status_code=400,
            submitted=submitted_statuses,
        )
    except RuntimeError as exc:
        subject = await run_in_threadpool(require_assigned, database, user, subject_id)
        roster = await run_in_threadpool(_roster, database, subject_id)
        request.session["flash"] = {"kind": "error", "message": str(exc)}
        return _attendance_page(
            request,
            database,
            subject,
            roster,
            selected_date,
            status_code=503,
            submitted=submitted_statuses,
        )

    marked_count = await run_in_threadpool(_marked_student_count, database, session_id, roster)
    remaining = max(len(roster) - marked_count, 0)
    request.session["flash"] = {
        "kind": "success",
        "message": (
            f"Attendance saved for all {len(roster)} students."
            if remaining == 0
            else f"Attendance saved. {remaining} student(s) still need to be marked."
        ),
    }
    return RedirectResponse(
        f"/teacher/subjects/{subject_id}/attendance/new?class_date={selected_date.isoformat()}",
        status_code=303,
    )
