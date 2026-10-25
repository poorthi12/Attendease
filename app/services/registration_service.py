import re
from collections import defaultdict
from datetime import datetime, timezone

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.models.student import student_document
from app.models.teacher import teacher_document
from app.models.user import user_document
from app.schemas.registration import StudentSignup, TeacherSignup
from app.security.password import hash_password
from app.services.admin_bootstrap import first_admin_setup_available
from app.services.atomic_write import atomic_write_or_compensate


class AdminSetupRequired(Exception):
    pass


class CurriculumUnavailable(Exception):
    pass


class SignupAlreadyExists(Exception):
    pass


def subject_groups(database: Database) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    rows = database.subjects.find({"active": {"$ne": False}}).sort(
        [("department", 1), ("academic_year", 1), ("semester", 1), ("code", 1)]
    ).limit(1000)
    for subject in rows:
        key = (subject.get("department", ""), subject.get("academic_year", ""), subject.get("semester", ""))
        grouped[key].append(subject)

    def semester_sort_key(value: str) -> tuple[int, str]:
        match = re.search(r"\d+", value)
        return (int(match.group()) if match else 999, value.casefold())

    result = []
    groups = sorted(
        grouped.items(),
        key=lambda item: (
            item[0][0].casefold(),
            item[0][1].casefold(),
            semester_sort_key(item[0][2]),
        ),
    )
    for (department, academic_year, semester), subjects in groups:
        if len(subjects) != 8:
            continue
        subjects.sort(
            key=lambda subject: (
                subject.get("code", "").casefold(),
                subject.get("name", "").casefold(),
            )
        )
        result.append(
            {
                "key": str(subjects[0]["_id"]),
                "department": department,
                "academic_year": academic_year,
                "semester": semester,
                "subjects": [
                    {"id": str(subject["_id"]), "code": subject["code"], "name": subject["name"]}
                    for subject in subjects
                ],
            }
        )
    return result


def _check_signup_allowed(database: Database) -> None:
    if first_admin_setup_available(database):
        raise AdminSetupRequired


def _signup_write(database: Database, account: dict, profile: dict, edges: list[dict], action: str, details: dict):
    audit_id = ObjectId()
    audit = {
        "_id": audit_id,
        "actor_id": account["_id"],
        "action": action,
        "target_id": profile["_id"],
        "details": details,
        "created_at": datetime.now(timezone.utc),
    }

    def write(session):
        options = {"session": session} if session is not None else {}
        database.users.insert_one(account, **options)
        collection = database.students if account["role"] == "student" else database.teachers
        collection.insert_one(profile, **options)
        edge_collection = database.enrollments if account["role"] == "student" else database.subject_assignments
        if edges:
            edge_collection.insert_many(edges, ordered=True, **options)
        database.audit_logs.insert_one(audit, **options)

    def rollback():
        database.audit_logs.delete_one({"_id": audit_id})
        if account["role"] == "student":
            database.enrollments.delete_many({"student_id": profile["_id"]})
            database.students.delete_one({"_id": profile["_id"]})
        else:
            database.subject_assignments.delete_many({"teacher_id": profile["_id"]})
            database.teachers.delete_one({"_id": profile["_id"]})
        database.users.delete_one({"_id": account["_id"]})

    try:
        atomic_write_or_compensate(database, write, rollback)
    except (DuplicateKeyError, RuntimeError) as exc:
        cause = exc.__cause__ if isinstance(exc, RuntimeError) else exc
        if isinstance(cause, DuplicateKeyError):
            raise SignupAlreadyExists from exc
        raise


def create_student_signup(database: Database, signup: StudentSignup) -> dict:
    _check_signup_allowed(database)
    groups = subject_groups(database)
    group = next((item for item in groups if item["key"] == signup.group_id), None)
    selected = set(signup.subject_ids)
    valid_ids = {subject["id"] for subject in group["subjects"]} if group else set()
    if not group or not selected or not selected.issubset(valid_ids):
        raise CurriculumUnavailable

    now = datetime.now(timezone.utc)
    account = user_document(signup.name, str(signup.email), "student", hash_password(signup.password))
    profile = student_document(
        account["_id"], signup.usn, signup.branch, group["department"], group["academic_year"]
    )
    profile["semester"] = group["semester"]
    profile["created_at"] = now
    edges = [
        {
            "_id": ObjectId(),
            "student_id": profile["_id"],
            "subject_id": ObjectId(subject_id),
            "active": True,
            "created_at": now,
        }
        for subject_id in signup.subject_ids
    ]
    _signup_write(
        database,
        account,
        profile,
        edges,
        "student.registered",
        {"semester": group["semester"], "subject_ids": signup.subject_ids},
    )
    return account


def create_teacher_signup(database: Database, signup: TeacherSignup) -> dict:
    _check_signup_allowed(database)
    groups = subject_groups(database)
    valid_ids = {
        subject["id"]
        for group in groups
        if group["department"].casefold() == signup.department.casefold()
        for subject in group["subjects"]
    }
    selected = set(signup.subject_ids)
    if not valid_ids or not selected or not selected.issubset(valid_ids):
        raise CurriculumUnavailable

    now = datetime.now(timezone.utc)
    account = user_document(signup.name, str(signup.email), "teacher", hash_password(signup.password))
    profile = teacher_document(account["_id"], signup.department)
    profile["created_at"] = now
    edges = [
        {
            "_id": ObjectId(),
            "teacher_id": profile["_id"],
            "subject_id": ObjectId(subject_id),
            "active": True,
            "created_at": now,
        }
        for subject_id in signup.subject_ids
    ]
    _signup_write(
        database,
        account,
        profile,
        edges,
        "teacher.registered",
        {"subject_ids": signup.subject_ids},
    )
    return account
