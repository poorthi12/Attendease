from bson import ObjectId

from app.security.password import hash_password
from tests.conftest import csrf_from


def test_enrollment_validation_rejects_inactive_entities(app_and_client, database):
    _, client = app_and_client
    admin_id = ObjectId()
    database.users.insert_one({"_id": admin_id, "name": "Admin", "email": "admin@example.edu", "role": "admin", "password_hash": hash_password("a-secure-test-password"), "is_active": True})
    student_id, subject_id = ObjectId(), ObjectId()
    database.students.insert_one({"_id": student_id, "user_id": ObjectId(), "usn": "1AA01", "active": False})
    database.subjects.insert_one({"_id": subject_id, "code": "CS101", "name": "Inactive", "active": True})
    csrf = csrf_from(client, "/login/admin")
    client.post("/login/admin", data={"identifier": "admin@example.edu", "password": "a-secure-test-password", "csrf": csrf})
    csrf = csrf_from(client, "/admin/assignments")
    response = client.post("/admin/assignments/enrollment", data={"student_id": str(student_id), "subject_id": str(subject_id), "csrf": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert database.enrollments.count_documents({}) == 0


def test_duplicate_email_and_subject_code_indexes_are_enforced(database):
    database.users.insert_one({"email": "same@example.edu", "role": "student"})
    database.subjects.insert_one({"code": "CS101"})
    import pytest
    from pymongo.errors import DuplicateKeyError
    with pytest.raises(DuplicateKeyError):
        database.users.insert_one({"email": "same@example.edu", "role": "teacher"})
    with pytest.raises(DuplicateKeyError):
        database.subjects.insert_one({"code": "CS101"})
