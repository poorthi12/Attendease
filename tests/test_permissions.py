from bson import ObjectId

from app.security.password import hash_password
from app.services.atomic_write import atomic_write_or_compensate
from tests.conftest import csrf_from


def _login(client, email, password, role):
    csrf = csrf_from(client, f"/login/{role}")
    return client.post(f"/login/{role}", data={"identifier": email, "password": password, "csrf": csrf}, follow_redirects=False)


def test_student_cannot_access_admin_tools(app_and_client, database):
    _, client = app_and_client
    password = "a-secure-test-password"
    database.users.insert_one({"_id": ObjectId(), "name": "Student", "email": "student@example.edu", "role": "student", "password_hash": hash_password(password), "is_active": True})
    assert _login(client, "student@example.edu", password, "student").headers["location"] == "/student"
    assert client.get("/admin/students").status_code == 403


def test_teacher_cannot_access_admin_tools(app_and_client, database):
    _, client = app_and_client
    password = "a-secure-test-password"
    database.users.insert_one({"_id": ObjectId(), "name": "Teacher", "email": "teacher@example.edu", "role": "teacher", "password_hash": hash_password(password), "is_active": True})
    _login(client, "teacher@example.edu", password, "teacher")
    assert client.get("/admin").status_code == 403


def test_public_admin_signup_does_not_exist(app_and_client):
    _, client = app_and_client
    assert client.get("/register/admin").status_code == 404


def test_admin_can_create_student_with_argon2_hash(app_and_client, database):
    _, client = app_and_client
    password = "a-secure-test-password"
    database.users.insert_one({"_id": ObjectId(), "name": "Admin", "email": "admin@example.edu", "role": "admin", "password_hash": hash_password(password), "is_active": True})
    csrf = csrf_from(client, "/login/admin")
    client.post("/login/admin", data={"identifier": "admin@example.edu", "password": password, "csrf": csrf})
    csrf = csrf_from(client, "/admin/students")
    response = client.post("/admin/students", data={"name": "New Student", "email": "new@example.edu", "password": "a-different-secure-password", "usn": "1AA99", "branch": "CSE", "department": "Engineering", "academic_year": "2026-27", "csrf": csrf}, follow_redirects=False)
    assert response.status_code == 303
    account = database.users.find_one({"email": "new@example.edu"})
    profile = database.students.find_one({"usn": "1AA99"})
    assert account and account["password_hash"].startswith("$argon2id$")
    assert profile and profile["user_id"] == account["_id"]


def test_admin_deactivation_preserves_history_and_disables_enrollment(app_and_client, database):
    _, client = app_and_client
    password, admin_id = "a-secure-test-password", ObjectId()
    student_user, student_id, subject_id = ObjectId(), ObjectId(), ObjectId()
    database.users.insert_many([
        {"_id": admin_id, "name": "Admin", "email": "admin@example.edu", "role": "admin", "password_hash": hash_password(password), "is_active": True},
        {"_id": student_user, "name": "Student", "email": "student@example.edu", "role": "student", "password_hash": hash_password(password), "is_active": True},
    ])
    database.students.insert_one({"_id": student_id, "user_id": student_user, "usn": "1AA01", "active": True})
    database.enrollments.insert_one({"student_id": student_id, "subject_id": subject_id, "active": True})
    database.attendance_records.insert_one({"student_id": student_id, "subject_id": subject_id, "date": "2026-01-01", "status": "present"})
    csrf = csrf_from(client, "/login/admin")
    client.post("/login/admin", data={"identifier": "admin@example.edu", "password": password, "csrf": csrf})
    csrf = csrf_from(client, "/admin/students")
    response = client.post(f"/admin/students/{student_id}/deactivate", data={"csrf": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert database.students.find_one({"_id": student_id})["active"] is False
    assert database.users.find_one({"_id": student_user})["is_active"] is False
    assert database.enrollments.find_one({"student_id": student_id})["active"] is False
    assert database.attendance_records.count_documents({"student_id": student_id}) == 1


def test_compensating_fallback_removes_partial_writes(database):
    def operation(_session):
        database.departments.insert_one({"key": "temporary"})
        raise RuntimeError("simulated write failure")
    def compensate():
        database.departments.delete_many({"key": "temporary"})
    import pytest
    with pytest.raises(RuntimeError, match="rolled back"):
        atomic_write_or_compensate(database, operation, compensate)
    assert database.departments.count_documents({"key": "temporary"}) == 0
