from datetime import date

from bson import ObjectId

from app.security.password import hash_password
from tests.conftest import csrf_from


def test_teacher_cannot_view_unassigned_subject_roster(app_and_client, database):
    _, client = app_and_client
    password = "a-secure-test-password"
    user_id, teacher_id = ObjectId(), ObjectId()
    assigned, unassigned = ObjectId(), ObjectId()
    database.users.insert_one({"_id": user_id, "name": "Teacher", "email": "teacher@example.edu", "role": "teacher", "password_hash": hash_password(password), "is_active": True})
    database.teachers.insert_one({"_id": teacher_id, "user_id": user_id, "department": "Engineering", "active": True})
    database.subjects.insert_many([
        {"_id": assigned, "code": "CS101", "name": "Assigned", "active": True},
        {"_id": unassigned, "code": "CS102", "name": "Private", "active": True},
    ])
    database.subject_assignments.insert_one({"teacher_id": teacher_id, "subject_id": assigned, "active": True})
    csrf = csrf_from(client, "/login/teacher")
    client.post("/login/teacher", data={"identifier": "teacher@example.edu", "password": password, "csrf": csrf})
    assert client.get(f"/teacher/subjects/{assigned}/students").status_code == 200
    assert client.get(f"/teacher/subjects/{unassigned}/students").status_code == 404


def test_teacher_cannot_submit_attendance_for_unassigned_subject(app_and_client, database):
    _, client = app_and_client
    password = "a-secure-test-password"
    user_id, teacher_id, subject = ObjectId(), ObjectId(), ObjectId()
    database.users.insert_one({"_id": user_id, "name": "Teacher", "email": "teacher@example.edu", "role": "teacher", "password_hash": hash_password(password), "is_active": True})
    database.teachers.insert_one({"_id": teacher_id, "user_id": user_id, "department": "Engineering", "active": True})
    database.subjects.insert_one({"_id": subject, "code": "CS101", "name": "Private", "active": True})
    csrf = csrf_from(client, "/login/teacher")
    client.post("/login/teacher", data={"identifier": "teacher@example.edu", "password": password, "csrf": csrf})
    response = client.get(f"/teacher/subjects/{subject}/attendance/new")
    assert response.status_code == 404


def test_teacher_marks_complete_roster_once(app_and_client, database):
    _, client = app_and_client
    password = "a-secure-test-password"
    teacher_user_id, teacher_id = ObjectId(), ObjectId()
    student_user_id, student_id, subject_id = ObjectId(), ObjectId(), ObjectId()
    database.users.insert_many([
        {"_id": teacher_user_id, "name": "Teacher", "email": "teacher@example.edu", "role": "teacher", "password_hash": hash_password(password), "is_active": True},
        {"_id": student_user_id, "name": "Student", "email": "student@example.edu", "role": "student", "password_hash": hash_password(password), "is_active": True},
    ])
    database.teachers.insert_one({"_id": teacher_id, "user_id": teacher_user_id, "department": "Engineering", "active": True})
    database.students.insert_one({"_id": student_id, "user_id": student_user_id, "usn": "1AA01", "branch": "CSE", "department": "Engineering", "academic_year": "2026", "active": True})
    database.subjects.insert_one({"_id": subject_id, "code": "CS101", "name": "Foundations", "active": True})
    database.subject_assignments.insert_one({"teacher_id": teacher_id, "subject_id": subject_id, "active": True})
    database.enrollments.insert_one({"student_id": student_id, "subject_id": subject_id, "active": True})
    csrf = csrf_from(client, "/login/teacher")
    client.post("/login/teacher", data={"identifier": "teacher@example.edu", "password": password, "csrf": csrf})
    path = f"/teacher/subjects/{subject_id}/attendance/new"
    csrf = csrf_from(client, path)
    payload = {"csrf": csrf, "class_date": date.today().isoformat(), f"status_{student_id}": "absent"}
    response = client.post(path, data=payload, follow_redirects=False)
    assert response.status_code == 303
    assert database.attendance_sessions.count_documents({"subject_id": subject_id, "status": "finalized"}) == 1
    record = database.attendance_records.find_one({"student_id": student_id, "subject_id": subject_id})
    assert record and record["status"] == "absent"
    csrf = csrf_from(client, path)
    manipulated = {"csrf": csrf, "class_date": date(2026, 1, 1).isoformat(), f"status_{student_id}": "present", f"status_{ObjectId()}": "present"}
    assert client.post(path, data=manipulated, follow_redirects=False).status_code == 400
    assert database.attendance_sessions.count_documents({"subject_id": subject_id, "date": date(2026, 1, 1).isoformat()}) == 0
    csrf = csrf_from(client, path)
    payload["csrf"] = csrf
    response = client.post(path, data=payload, follow_redirects=False)
    assert response.status_code == 400
    assert database.attendance_sessions.count_documents({"subject_id": subject_id}) == 1


def test_all_role_pages_render_with_empty_data(app_and_client, database):
    _, client = app_and_client
    password = "a-secure-test-password"
    student_user_id, teacher_user_id, admin_id = ObjectId(), ObjectId(), ObjectId()
    database.users.insert_many([
        {"_id": student_user_id, "name": "Student", "email": "student@example.edu", "role": "student", "password_hash": hash_password(password), "is_active": True},
        {"_id": teacher_user_id, "name": "Teacher", "email": "teacher@example.edu", "role": "teacher", "password_hash": hash_password(password), "is_active": True},
        {"_id": admin_id, "name": "Admin", "email": "admin@example.edu", "role": "admin", "password_hash": hash_password(password), "is_active": True},
    ])
    database.students.insert_one({"_id": ObjectId(), "user_id": student_user_id, "usn": "1AA01", "branch": "CSE", "department": "Engineering", "academic_year": "2026", "active": True})
    database.teachers.insert_one({"_id": ObjectId(), "user_id": teacher_user_id, "department": "Engineering", "active": True})
    for role, email, paths in [
        ("student", "student@example.edu", ["/student", "/student/profile", "/student/subjects", "/student/attendance", "/student/absent-dates"]),
        ("teacher", "teacher@example.edu", ["/teacher", "/teacher/subjects", "/teacher/attendance-history", "/teacher/analytics"]),
        ("admin", "admin@example.edu", ["/admin", "/admin/students", "/admin/teachers", "/admin/subjects", "/admin/assignments"]),
    ]:
        csrf = csrf_from(client, f"/login/{role}")
        client.post(f"/login/{role}", data={"identifier": email, "password": password, "csrf": csrf})
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, (path, response.text[:300])


def test_student_cannot_submit_teacher_attendance_form(app_and_client, database):
    _, client = app_and_client
    password, user_id = "a-secure-test-password", ObjectId()
    database.users.insert_one({"_id": user_id, "name": "Student", "email": "student@example.edu", "role": "student", "password_hash": hash_password(password), "is_active": True})
    csrf = csrf_from(client, "/login/student")
    client.post("/login/student", data={"identifier": "student@example.edu", "password": password, "csrf": csrf})
    response = client.post(f"/teacher/subjects/{ObjectId()}/attendance/new", data={"csrf": csrf, "class_date": date.today().isoformat()})
    assert response.status_code == 403
