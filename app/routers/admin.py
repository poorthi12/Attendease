import logging
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.database import Database

from app.database import get_database
from app.schemas.student import StudentCreate
from app.schemas.subject import SubjectCreate
from app.schemas.teacher import TeacherCreate
from app.security.password import hash_password
from app.security.permissions import require_role
from app.security.sessions import verify_csrf
from app.services.atomic_write import atomic_write_or_compensate
from app.utils.responses import render

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = Depends(require_role("admin"))
logger = logging.getLogger(__name__)


def _redirect(request: Request, message: str, kind: str = "success", path: str = "/admin"):
    request.session["flash"] = {"kind": kind, "message": message}
    return RedirectResponse(path, status_code=303)


def _audit(database: Database, actor: dict, action: str, target: ObjectId, details: dict | None = None, *, audit_id: ObjectId | None = None, session=None):
    row = {"actor_id": ObjectId(actor["id"]), "action": action, "target_id": target, "details": details or {}, "created_at": datetime.now(timezone.utc)}
    if audit_id:
        row["_id"] = audit_id
    database.audit_logs.insert_one(row, **({"session": session} if session is not None else {}))


def _id(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("")
def dashboard(request: Request, database: Database = Depends(get_database), user: dict = admin_only):
    counts = {
        "students": database.students.count_documents({"active": {"$ne": False}}),
        "teachers": database.teachers.count_documents({"active": {"$ne": False}}),
        "subjects": database.subjects.count_documents({"active": {"$ne": False}}),
        "sessions": database.attendance_sessions.count_documents({"status": "finalized"}),
    }
    recent = list(database.audit_logs.find().sort("created_at", -1).limit(8))
    for row in recent:
        row["id"] = str(row.pop("_id"))
        actor = database.users.find_one({"_id": row.get("actor_id")})
        row["actor_name"] = actor.get("name", "System") if actor else "System"
    return render(request, "admin/dashboard.html", title="Administration", counts=counts, recent=recent)


@router.get("/students")
def students_page(request: Request, q: str = "", database: Database = Depends(get_database), user: dict = admin_only):
    rows = []
    for student in database.students.find().sort("usn", 1).limit(500):
        account = database.users.find_one({"_id": student["user_id"]}) or {}
        student.update({"name": account.get("name", ""), "email": account.get("email", ""), "active": student.get("active", True) and account.get("is_active", True)})
        rows.append(_id(student))
    query = q.strip().casefold()
    if query:
        rows = [row for row in rows if query in row.get("name", "").casefold() or query in row.get("usn", "").casefold() or query in row.get("email", "").casefold()]
    return render(request, "admin/students.html", title="Students", students=rows, query=q)


@router.post("/students")
def create_student(
    request: Request,
    name: str = Form(...), email: str = Form(...), password: str = Form(...), usn: str = Form(...),
    branch: str = Form(...), department: str = Form(...), academic_year: str = Form(...), csrf: str = Form(...),
    database: Database = Depends(get_database), user: dict = admin_only,
):
    verify_csrf(request, csrf)
    try:
        values = StudentCreate.model_validate(locals())
        now = datetime.now(timezone.utc)
        account_id = ObjectId()
        student_id = ObjectId()
        account = {"_id": account_id, "name": values.name.strip(), "email": str(values.email).lower(), "role": "student", "password_hash": hash_password(values.password), "is_active": True, "created_at": now}
        profile = {"_id": student_id, "user_id": account_id, "usn": values.usn, "branch": values.branch.strip(), "department": values.department.strip(), "academic_year": values.academic_year.strip(), "active": True, "created_at": now}
        audit_id = ObjectId()
        def write(session):
            options = {"session": session} if session is not None else {}
            database.users.insert_one(account, **options)
            database.students.insert_one(profile, **options)
            _audit(database, user, "student.created", student_id, audit_id=audit_id, session=session)
        def rollback():
            database.audit_logs.delete_one({"_id": audit_id})
            database.students.delete_one({"_id": student_id})
            database.users.delete_one({"_id": account_id})
        atomic_write_or_compensate(database, write, rollback)
        return _redirect(request, "Student account created.", path="/admin/students")
    except (ValidationError, ValueError) as exc:
        return _redirect(request, str(exc)[:220], "error", "/admin/students")
    except DuplicateKeyError:
        return _redirect(request, "That email address or USN is already in use.", "error", "/admin/students")
    except RuntimeError:
        return _redirect(request, "The student could not be saved completely. Please try again.", "error", "/admin/students")
    except PyMongoError:
        return _redirect(request, "The student could not be saved. Check the database connection and try again.", "error", "/admin/students")


@router.post("/students/{student_id}/deactivate")
def deactivate_student(student_id: str, request: Request, csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        student = database.students.find_one({"_id": ObjectId(student_id)})
        if not student:
            return _redirect(request, "Student not found.", "error", "/admin/students")
        account = database.users.find_one({"_id": student["user_id"]}) or {}
        enrollments = list(database.enrollments.find({"student_id": student["_id"]}))
        audit_id = ObjectId()
        def deactivate(session):
            options = {"session": session} if session is not None else {}
            database.students.update_one({"_id": student["_id"]}, {"$set": {"active": False}}, **options)
            database.users.update_one({"_id": student["user_id"]}, {"$set": {"is_active": False}}, **options)
            database.enrollments.update_many({"student_id": student["_id"]}, {"$set": {"active": False}}, **options)
            _audit(database, user, "student.deactivated", student["_id"], audit_id=audit_id, session=session)
        def restore():
            database.audit_logs.delete_one({"_id": audit_id})
            database.students.update_one({"_id": student["_id"]}, {"$set": {"active": student.get("active", True)}})
            if account:
                database.users.update_one({"_id": student["user_id"]}, {"$set": {"is_active": account.get("is_active", True)}})
            for enrollment in enrollments:
                database.enrollments.update_one({"_id": enrollment["_id"]}, {"$set": {"active": enrollment.get("active", True)}})
        atomic_write_or_compensate(database, deactivate, restore)
        return _redirect(request, "Student access deactivated. Attendance history was preserved.", path="/admin/students")
    except Exception as exc:
        logger.error("Student deactivation failed (%s).", type(exc).__name__)
        return _redirect(request, "The student could not be deactivated.", "error", "/admin/students")


@router.get("/teachers")
def teachers_page(request: Request, q: str = "", database: Database = Depends(get_database), user: dict = admin_only):
    rows = []
    for teacher in database.teachers.find().sort("department", 1).limit(500):
        account = database.users.find_one({"_id": teacher["user_id"]}) or {}
        teacher.update({"name": account.get("name", ""), "email": account.get("email", ""), "active": teacher.get("active", True) and account.get("is_active", True)})
        rows.append(_id(teacher))
    query = q.strip().casefold()
    if query:
        rows = [row for row in rows if query in row.get("name", "").casefold() or query in row.get("email", "").casefold()]
    return render(request, "admin/teachers.html", title="Teachers", teachers=rows, query=q)


@router.post("/teachers")
def create_teacher(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...), department: str = Form(...), csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        values = TeacherCreate.model_validate(locals())
        now, account_id, teacher_id = datetime.now(timezone.utc), ObjectId(), ObjectId()
        account = {"_id": account_id, "name": values.name.strip(), "email": str(values.email).lower(), "role": "teacher", "password_hash": hash_password(values.password), "is_active": True, "created_at": now}
        profile = {"_id": teacher_id, "user_id": account_id, "department": values.department.strip(), "active": True, "created_at": now}
        audit_id = ObjectId()
        def write(session):
            options = {"session": session} if session is not None else {}
            database.users.insert_one(account, **options)
            database.teachers.insert_one(profile, **options)
            _audit(database, user, "teacher.created", teacher_id, audit_id=audit_id, session=session)
        def rollback():
            database.audit_logs.delete_one({"_id": audit_id})
            database.teachers.delete_one({"_id": teacher_id})
            database.users.delete_one({"_id": account_id})
        atomic_write_or_compensate(database, write, rollback)
        return _redirect(request, "Teacher account created.", path="/admin/teachers")
    except (ValidationError, ValueError) as exc:
        return _redirect(request, str(exc)[:220], "error", "/admin/teachers")
    except DuplicateKeyError:
        return _redirect(request, "That email address is already in use.", "error", "/admin/teachers")
    except RuntimeError:
        return _redirect(request, "The teacher could not be saved completely. Please try again.", "error", "/admin/teachers")
    except PyMongoError:
        return _redirect(request, "The teacher could not be saved.", "error", "/admin/teachers")


@router.post("/teachers/{teacher_id}/deactivate")
def deactivate_teacher(teacher_id: str, request: Request, csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        teacher = database.teachers.find_one({"_id": ObjectId(teacher_id)})
        if not teacher:
            return _redirect(request, "Teacher not found.", "error", "/admin/teachers")
        account = database.users.find_one({"_id": teacher["user_id"]}) or {}
        assignments = list(database.subject_assignments.find({"teacher_id": teacher["_id"]}))
        audit_id = ObjectId()
        def deactivate(session):
            options = {"session": session} if session is not None else {}
            database.teachers.update_one({"_id": teacher["_id"]}, {"$set": {"active": False}}, **options)
            database.users.update_one({"_id": teacher["user_id"]}, {"$set": {"is_active": False}}, **options)
            database.subject_assignments.update_many({"teacher_id": teacher["_id"]}, {"$set": {"active": False}}, **options)
            _audit(database, user, "teacher.deactivated", teacher["_id"], audit_id=audit_id, session=session)
        def restore():
            database.audit_logs.delete_one({"_id": audit_id})
            database.teachers.update_one({"_id": teacher["_id"]}, {"$set": {"active": teacher.get("active", True)}})
            if account:
                database.users.update_one({"_id": teacher["user_id"]}, {"$set": {"is_active": account.get("is_active", True)}})
            for assignment in assignments:
                database.subject_assignments.update_one({"_id": assignment["_id"]}, {"$set": {"active": assignment.get("active", True)}})
        atomic_write_or_compensate(database, deactivate, restore)
        return _redirect(request, "Teacher access deactivated. Existing attendance history was preserved.", path="/admin/teachers")
    except Exception as exc:
        logger.error("Teacher deactivation failed (%s).", type(exc).__name__)
        return _redirect(request, "The teacher could not be deactivated.", "error", "/admin/teachers")


@router.get("/subjects")
def subjects_page(request: Request, database: Database = Depends(get_database), user: dict = admin_only):
    subjects = [_id(item) for item in database.subjects.find().sort("code", 1).limit(500)]
    return render(request, "admin/subjects.html", title="Subjects", subjects=subjects)


@router.post("/subjects")
def create_subject(request: Request, code: str = Form(...), name: str = Form(...), department: str = Form(...), academic_year: str = Form(...), semester: str = Form(...), csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        values = SubjectCreate.model_validate(locals())
        semester_count = database.subjects.count_documents(
            {
                "department": values.department,
                "academic_year": values.academic_year,
                "semester": values.semester,
                "active": {"$ne": False},
            }
        )
        if semester_count >= 8:
            return _redirect(
                request,
                "A department, academic year, and semester can have at most 8 active subjects.",
                "error",
                "/admin/subjects",
            )
        subject_id = ObjectId()
        audit_id = ObjectId()
        document = {"_id": subject_id, "code": values.code, "name": values.name.strip(), "department": values.department.strip(), "academic_year": values.academic_year.strip(), "semester": values.semester.strip(), "active": True, "created_at": datetime.now(timezone.utc)}
        def create(session):
            database.subjects.insert_one(document, **({"session": session} if session is not None else {}))
            _audit(database, user, "subject.created", subject_id, audit_id=audit_id, session=session)
        def rollback():
            database.audit_logs.delete_one({"_id": audit_id})
            database.subjects.delete_one({"_id": subject_id})
        atomic_write_or_compensate(database, create, rollback)
        return _redirect(request, "Subject created.", path="/admin/subjects")
    except ValidationError as exc:
        return _redirect(request, str(exc)[:220], "error", "/admin/subjects")
    except DuplicateKeyError:
        return _redirect(request, "That subject code already exists.", "error", "/admin/subjects")
    except RuntimeError:
        return _redirect(request, "The subject could not be saved completely. Please try again.", "error", "/admin/subjects")
    except PyMongoError:
        return _redirect(request, "The subject could not be saved.", "error", "/admin/subjects")


@router.post("/subjects/{subject_id}/deactivate")
def deactivate_subject(subject_id: str, request: Request, csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        oid = ObjectId(subject_id)
        subject = database.subjects.find_one({"_id": oid})
        if not subject:
            return _redirect(request, "Subject not found.", "error", "/admin/subjects")
        assignments = list(database.subject_assignments.find({"subject_id": oid}))
        enrollments = list(database.enrollments.find({"subject_id": oid}))
        audit_id = ObjectId()
        def deactivate(session):
            options = {"session": session} if session is not None else {}
            database.subjects.update_one({"_id": oid}, {"$set": {"active": False}}, **options)
            database.subject_assignments.update_many({"subject_id": oid}, {"$set": {"active": False}}, **options)
            database.enrollments.update_many({"subject_id": oid}, {"$set": {"active": False}}, **options)
            _audit(database, user, "subject.deactivated", oid, audit_id=audit_id, session=session)
        def restore():
            database.audit_logs.delete_one({"_id": audit_id})
            database.subjects.update_one({"_id": oid}, {"$set": {"active": subject.get("active", True)}})
            for assignment in assignments:
                database.subject_assignments.update_one({"_id": assignment["_id"]}, {"$set": {"active": assignment.get("active", True)}})
            for enrollment in enrollments:
                database.enrollments.update_one({"_id": enrollment["_id"]}, {"$set": {"active": enrollment.get("active", True)}})
        atomic_write_or_compensate(database, deactivate, restore)
        return _redirect(request, "Subject deactivated. Attendance history was preserved.", path="/admin/subjects")
    except Exception as exc:
        logger.error("Subject deactivation failed (%s).", type(exc).__name__)
        return _redirect(request, "The subject could not be deactivated.", "error", "/admin/subjects")


@router.get("/assignments")
def assignments_page(request: Request, database: Database = Depends(get_database), user: dict = admin_only):
    teachers, students, subjects = [], [], []
    for profile in database.teachers.find({"active": {"$ne": False}}):
        account = database.users.find_one({"_id": profile["user_id"], "is_active": True}) or {}
        teachers.append({"id": str(profile["_id"]), "name": account.get("name", ""), "department": profile.get("department", "")})
    for profile in database.students.find({"active": {"$ne": False}}):
        account = database.users.find_one({"_id": profile["user_id"], "is_active": True}) or {}
        students.append({"id": str(profile["_id"]), "name": account.get("name", ""), "usn": profile.get("usn", "")})
    for subject in database.subjects.find({"active": {"$ne": False}}):
        subjects.append({"id": str(subject["_id"]), "code": subject.get("code", ""), "name": subject.get("name", "")})
    assignments = []
    for row in database.subject_assignments.find({"active": {"$ne": False}}):
        teacher = next((item for item in teachers if item["id"] == str(row["teacher_id"])), None)
        subject = next((item for item in subjects if item["id"] == str(row["subject_id"])), None)
        if teacher and subject:
            assignments.append({"id": str(row["_id"]), "teacher": teacher["name"], "subject": f"{subject['code']} · {subject['name']}"})
    enrollments = []
    for row in database.enrollments.find({"active": {"$ne": False}}).limit(1000):
        student = next((item for item in students if item["id"] == str(row["student_id"])), None)
        subject = next((item for item in subjects if item["id"] == str(row["subject_id"])), None)
        if student and subject:
            enrollments.append({"id": str(row["_id"]), "student": f"{student['name']} · {student['usn']}", "subject": subject["code"]})
    departments = list(database.departments.find({"active": {"$ne": False}}).sort("name", 1))
    for row in departments:
        row["id"] = str(row.pop("_id"))
    return render(request, "admin/assignments.html", title="Assignments & enrollment", teachers=teachers, students=students, subjects=subjects, assignments=assignments, enrollments=enrollments, departments=departments)


@router.post("/assignments/teacher")
def assign_teacher(request: Request, teacher_id: str = Form(...), subject_id: str = Form(...), csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        teacher_oid, subject_oid = ObjectId(teacher_id), ObjectId(subject_id)
        if not database.teachers.find_one({"_id": teacher_oid, "active": {"$ne": False}}) or not database.subjects.find_one({"_id": subject_oid, "active": {"$ne": False}}):
            return _redirect(request, "Choose an active teacher and subject.", "error", "/admin/assignments")
        before = database.subject_assignments.find_one({"teacher_id": teacher_oid, "subject_id": subject_oid})
        audit_id = ObjectId()
        def assign(session):
            options = {"session": session} if session is not None else {}
            database.subject_assignments.update_one({"teacher_id": teacher_oid, "subject_id": subject_oid}, {"$set": {"active": True}, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}}, upsert=True, **options)
            _audit(database, user, "teacher.assigned", subject_oid, {"teacher_id": str(teacher_oid)}, audit_id=audit_id, session=session)
        def rollback():
            database.audit_logs.delete_one({"_id": audit_id})
            if before:
                database.subject_assignments.update_one({"_id": before["_id"]}, {"$set": {"active": before.get("active", True)}})
            else:
                database.subject_assignments.delete_one({"teacher_id": teacher_oid, "subject_id": subject_oid})
        atomic_write_or_compensate(database, assign, rollback)
        return _redirect(request, "Teacher assigned to subject.", path="/admin/assignments")
    except DuplicateKeyError:
        return _redirect(request, "This teacher is already assigned to the subject.", "error", "/admin/assignments")
    except Exception as exc:
        logger.error("Teacher assignment could not be saved (%s).", type(exc).__name__)
        return _redirect(request, "Assignment could not be saved.", "error", "/admin/assignments")


@router.post("/assignments/enrollment")
def enroll_student(request: Request, student_id: str = Form(...), subject_id: str = Form(...), csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        student_oid, subject_oid = ObjectId(student_id), ObjectId(subject_id)
        if not database.students.find_one({"_id": student_oid, "active": {"$ne": False}}) or not database.subjects.find_one({"_id": subject_oid, "active": {"$ne": False}}):
            return _redirect(request, "Choose an active student and subject.", "error", "/admin/assignments")
        before = database.enrollments.find_one({"student_id": student_oid, "subject_id": subject_oid})
        audit_id = ObjectId()
        def enroll(session):
            options = {"session": session} if session is not None else {}
            database.enrollments.update_one({"student_id": student_oid, "subject_id": subject_oid}, {"$set": {"active": True}, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}}, upsert=True, **options)
            _audit(database, user, "student.enrolled", subject_oid, {"student_id": str(student_oid)}, audit_id=audit_id, session=session)
        def rollback():
            database.audit_logs.delete_one({"_id": audit_id})
            if before:
                database.enrollments.update_one({"_id": before["_id"]}, {"$set": {"active": before.get("active", True)}})
            else:
                database.enrollments.delete_one({"student_id": student_oid, "subject_id": subject_oid})
        atomic_write_or_compensate(database, enroll, rollback)
        return _redirect(request, "Student enrolled in subject.", path="/admin/assignments")
    except DuplicateKeyError:
        return _redirect(request, "This student is already enrolled in the subject.", "error", "/admin/assignments")
    except Exception as exc:
        logger.error("Student enrollment could not be saved (%s).", type(exc).__name__)
        return _redirect(request, "Enrollment could not be saved.", "error", "/admin/assignments")


@router.post("/departments")
def add_department(request: Request, name: str = Form(..., min_length=2, max_length=100), csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    normalized = " ".join(name.split())
    department_id, audit_id = ObjectId(), ObjectId()
    try:
        def add(session):
            options = {"session": session} if session is not None else {}
            database.departments.insert_one({"_id": department_id, "name": normalized, "key": normalized.casefold(), "active": True, "created_at": datetime.now(timezone.utc)}, **options)
            _audit(database, user, "department.created", department_id, {"name": normalized}, audit_id=audit_id, session=session)
        def rollback():
            database.audit_logs.delete_one({"_id": audit_id})
            database.departments.delete_one({"_id": department_id})
        atomic_write_or_compensate(database, add, rollback)
        return _redirect(request, "Department added.", path="/admin/assignments")
    except DuplicateKeyError:
        return _redirect(request, "That department already exists.", "error", "/admin/assignments")
    except PyMongoError:
        return _redirect(request, "Department could not be saved.", "error", "/admin/assignments")


@router.post("/assignments/teacher/{assignment_id}/deactivate")
def deactivate_assignment(assignment_id: str, request: Request, csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        oid = ObjectId(assignment_id)
        before = database.subject_assignments.find_one({"_id": oid})
        if not before:
            return _redirect(request, "Assignment not found.", "error", "/admin/assignments")
        audit_id = ObjectId()
        def remove(session):
            options = {"session": session} if session is not None else {}
            database.subject_assignments.update_one({"_id": oid}, {"$set": {"active": False}}, **options)
            _audit(database, user, "teacher.assignment_removed", oid, audit_id=audit_id, session=session)
        def restore():
            database.audit_logs.delete_one({"_id": audit_id})
            database.subject_assignments.update_one({"_id": oid}, {"$set": {"active": before.get("active", True)}})
        atomic_write_or_compensate(database, remove, restore)
        return _redirect(request, "Teacher assignment removed. Attendance history was preserved.", path="/admin/assignments")
    except Exception as exc:
        logger.error("Teacher assignment could not be deactivated (%s).", type(exc).__name__)
        return _redirect(request, "Assignment could not be removed.", "error", "/admin/assignments")


@router.post("/assignments/enrollment/{enrollment_id}/deactivate")
def deactivate_enrollment(enrollment_id: str, request: Request, csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        oid = ObjectId(enrollment_id)
        before = database.enrollments.find_one({"_id": oid})
        if not before:
            return _redirect(request, "Enrollment not found.", "error", "/admin/assignments")
        audit_id = ObjectId()
        def remove(session):
            options = {"session": session} if session is not None else {}
            database.enrollments.update_one({"_id": oid}, {"$set": {"active": False}}, **options)
            _audit(database, user, "student.unenrolled", oid, audit_id=audit_id, session=session)
        def restore():
            database.audit_logs.delete_one({"_id": audit_id})
            database.enrollments.update_one({"_id": oid}, {"$set": {"active": before.get("active", True)}})
        atomic_write_or_compensate(database, remove, restore)
        return _redirect(request, "Enrollment ended. Previous attendance was preserved.", path="/admin/assignments")
    except Exception as exc:
        logger.error("Student enrollment could not be deactivated (%s).", type(exc).__name__)
        return _redirect(request, "Enrollment could not be ended.", "error", "/admin/assignments")


@router.post("/departments/{department_id}/deactivate")
def deactivate_department(department_id: str, request: Request, csrf: str = Form(...), database: Database = Depends(get_database), user: dict = admin_only):
    verify_csrf(request, csrf)
    try:
        oid = ObjectId(department_id)
        before = database.departments.find_one({"_id": oid})
        if not before:
            return _redirect(request, "Department not found.", "error", "/admin/assignments")
        audit_id = ObjectId()
        def deactivate(session):
            options = {"session": session} if session is not None else {}
            database.departments.update_one({"_id": oid}, {"$set": {"active": False}}, **options)
            _audit(database, user, "department.deactivated", oid, audit_id=audit_id, session=session)
        def restore():
            database.audit_logs.delete_one({"_id": audit_id})
            database.departments.update_one({"_id": oid}, {"$set": {"active": before.get("active", True)}})
        atomic_write_or_compensate(database, deactivate, restore)
        return _redirect(request, "Department deactivated. Existing student, teacher, and subject records were preserved.", path="/admin/assignments")
    except Exception as exc:
        logger.error("Department deactivation failed (%s).", type(exc).__name__)
        return _redirect(request, "Department could not be deactivated.", "error", "/admin/assignments")
