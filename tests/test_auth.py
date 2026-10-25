from bson import ObjectId

from app.security.password import hash_password, verify_password
from tests.conftest import csrf_from


def test_argon2_password_hashing():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)
    assert not verify_password("anything", None)


def test_login_and_logout_rotate_session_and_require_csrf(app_and_client, database):
    _, client = app_and_client
    account_id = ObjectId()
    database.users.insert_one({"_id": account_id, "name": "Ada Student", "email": "ada@example.edu", "role": "student", "password_hash": hash_password("a-secure-test-password"), "is_active": True})
    csrf = csrf_from(client, "/login/student")
    response = client.post("/login/student", data={"identifier": "ada@example.edu", "password": "a-secure-test-password", "csrf": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/student"
    logout_csrf = csrf_from(client, "/student")
    response = client.post("/logout", data={"csrf": logout_csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert "attendease_session" in response.headers.get("set-cookie", "")


def test_login_requires_csrf(app_and_client, database):
    _, client = app_and_client
    response = client.post("/login/student", data={"identifier": "person@example.edu", "password": "password", "csrf": "invalid"}, follow_redirects=False)
    assert response.status_code == 403


def test_user_cannot_login_through_another_role(app_and_client, database):
    _, client = app_and_client
    database.users.insert_one({"_id": ObjectId(), "name": "A teacher", "email": "teacher@example.edu", "role": "teacher", "password_hash": hash_password("a-secure-test-password"), "is_active": True})
    csrf = csrf_from(client, "/login/student")
    response = client.post("/login/student", data={"identifier": "teacher@example.edu", "password": "a-secure-test-password", "csrf": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login/student"
    assert "/student" not in client.get("/student", follow_redirects=False).headers.get("location", "")
