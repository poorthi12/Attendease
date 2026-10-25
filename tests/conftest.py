import pytest
import mongomock
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.database import get_database
from app.main import create_app


@pytest.fixture
def database():
    client = mongomock.MongoClient(tz_aware=True)
    db = client["attendease_test"]
    db.users.create_index("email", unique=True)
    db.students.create_index("usn", unique=True)
    db.students.create_index("user_id", unique=True)
    db.teachers.create_index("user_id", unique=True)
    db.subjects.create_index("code", unique=True)
    db.subject_assignments.create_index([("teacher_id", 1), ("subject_id", 1)], unique=True)
    db.enrollments.create_index([("student_id", 1), ("subject_id", 1)], unique=True)
    db.attendance_sessions.create_index([("subject_id", 1), ("date", 1)], unique=True)
    db.attendance_records.create_index([("session_id", 1), ("student_id", 1)], unique=True)
    return db


@pytest.fixture
def app_and_client(database):
    settings = Settings(app_env="test", session_secret=SecretStr("test-session-secret-which-is-long-enough"), mongodb_url=None)
    app = create_app(settings)
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as client:
        yield app, client


def csrf_from(client, path="/"):
    response = client.get(path)
    import re
    match = re.search(r'name="csrf" value="([^"]+)"', response.text)
    assert match, f"CSRF token not found in {path} response"
    return match.group(1)
