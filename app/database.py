import logging
from threading import Lock

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
_client: MongoClient | None = None
_client_lock = Lock()
_indexes_lock = Lock()
_indexes_ready = False


def get_client(settings: Settings | None = None) -> MongoClient:
    global _client
    settings = settings or get_settings()
    if not settings.mongodb_url:
        raise RuntimeError("MongoDB is not configured. Set MONGODB_URL in the environment.")
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = MongoClient(
                    settings.mongodb_url.get_secret_value(),
                    appname="AttendEase",
                    connect=False,
                    serverSelectionTimeoutMS=5000,
                    maxPoolSize=50,
                    minPoolSize=0,
                    retryWrites=True,
                )
    return _client


def get_database() -> Database:
    """FastAPI dependency for the configured application database."""
    settings = get_settings()
    return get_client(settings)[settings.mongodb_database]


def close_client() -> None:
    global _client, _indexes_ready
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None
    _indexes_ready = False


def ensure_indexes(database: Database) -> None:
    """Create the small, stable index set once during application startup."""
    global _indexes_ready
    if _indexes_ready:
        return
    with _indexes_lock:
        if _indexes_ready:
            return
        database.users.create_index([("email", ASCENDING)], unique=True, name="user_email_unique")
        database.students.create_index([("usn", ASCENDING)], unique=True, name="student_usn_unique")
        database.students.create_index([("user_id", ASCENDING)], unique=True, name="student_user_unique")
        database.teachers.create_index([("user_id", ASCENDING)], unique=True, name="teacher_user_unique")
        database.subjects.create_index([("code", ASCENDING)], unique=True, name="subject_code_unique")
        database.subject_assignments.create_index(
            [("teacher_id", ASCENDING), ("subject_id", ASCENDING)], unique=True, name="assignment_unique"
        )
        database.subject_assignments.create_index([("teacher_id", ASCENDING), ("active", ASCENDING)])
        database.enrollments.create_index(
            [("student_id", ASCENDING), ("subject_id", ASCENDING)], unique=True, name="enrollment_unique"
        )
        database.enrollments.create_index([("subject_id", ASCENDING), ("active", ASCENDING)])
        database.attendance_sessions.create_index(
            [("subject_id", ASCENDING), ("date", ASCENDING)], unique=True, name="subject_date_unique"
        )
        database.attendance_sessions.create_index([("teacher_id", ASCENDING), ("date", ASCENDING)])
        database.attendance_records.create_index(
            [("session_id", ASCENDING), ("student_id", ASCENDING)], unique=True, name="session_student_unique"
        )
        database.attendance_records.create_index([("student_id", ASCENDING), ("date", ASCENDING)])
        database.attendance_records.create_index([("subject_id", ASCENDING), ("date", ASCENDING)])
        database.audit_logs.create_index([("created_at", ASCENDING)])
        database.departments.create_index([("key", ASCENDING)], unique=True, name="department_key_unique")
        database.auth_attempts.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
        _indexes_ready = True


def reset_index_state_for_tests() -> None:
    global _indexes_ready
    _indexes_ready = False
