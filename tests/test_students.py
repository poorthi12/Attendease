from bson import ObjectId

from app.security.password import hash_password
from tests.conftest import csrf_from


def test_student_records_are_scoped_to_signed_in_student(app_and_client, database):
    _, client = app_and_client
    password = "a-secure-test-password"
    first_user, second_user = ObjectId(), ObjectId()
    database.users.insert_many([
        {"_id": first_user, "name": "First Student", "email": "first@example.edu", "role": "student", "password_hash": hash_password(password), "is_active": True},
        {"_id": second_user, "name": "Second Student", "email": "second@example.edu", "role": "student", "password_hash": hash_password(password), "is_active": True},
    ])
    first, second, subject = ObjectId(), ObjectId(), ObjectId()
    database.students.insert_many([
        {"_id": first, "user_id": first_user, "usn": "1AA01", "branch": "CSE", "department": "Engineering", "academic_year": "2026", "active": True},
        {"_id": second, "user_id": second_user, "usn": "1AA02", "branch": "CSE", "department": "Engineering", "academic_year": "2026", "active": True},
    ])
    database.subjects.insert_one({"_id": subject, "code": "CS101", "name": "Foundations", "department": "Engineering", "academic_year": "2026", "semester": "1", "active": True})
    database.enrollments.insert_many([{"student_id": first, "subject_id": subject, "active": True}, {"student_id": second, "subject_id": subject, "active": True}])
    database.attendance_records.insert_many([
        {"student_id": first, "subject_id": subject, "date": "2026-01-01", "status": "present"},
        {"student_id": second, "subject_id": subject, "date": "2026-01-02", "status": "absent"},
    ])
    csrf = csrf_from(client, "/login/student")
    client.post("/login/student", data={"identifier": "first@example.edu", "password": password, "csrf": csrf})
    attendance = client.get("/student/attendance")
    assert attendance.status_code == 200
    assert "2026-01-01" in attendance.text
    assert "2026-01-02" not in attendance.text
    assert "Second Student" not in client.get("/student/profile?student_id=" + str(second)).text


def test_home_and_login_templates_render(app_and_client):
    _, client = app_and_client
    assert client.get("/").status_code == 200
    response = client.get("/login/teacher")
    assert response.status_code == 200
    assert "Teacher sign in" in response.text
    assert "/static/css/main.css" in response.text


def test_security_headers_static_asset_and_body_limit(app_and_client):
    _, client = app_and_client
    home = client.get("/")
    assert home.status_code == 200
    assert home.headers["x-frame-options"] == "DENY"
    assert home.headers["x-content-type-options"] == "nosniff"
    logo = client.get("/static/images/logo.svg")
    assert logo.status_code == 200 and "<svg" in logo.text
    oversized = client.post("/logout", content=b"x" * (1_048_577), headers={"content-type": "application/octet-stream"})
    assert oversized.status_code == 413
