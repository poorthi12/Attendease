import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pymongo.database import Database
from pydantic import ValidationError

from app.database import get_database
from app.schemas.auth import AdminRegistration, LoginCredentials
from app.services.auth_service import authenticate
from app.services.admin_bootstrap import (
    BootstrapAlreadyComplete,
    EmailAlreadyRegistered,
    create_first_admin,
    first_admin_setup_available,
)
from app.security.sessions import csrf_token, verify_csrf
from app.schemas.registration import StudentSignup, TeacherSignup
from app.services.registration_service import (
    AdminSetupRequired,
    CurriculumUnavailable,
    SignupAlreadyExists,
    create_student_signup,
    create_teacher_signup,
    subject_groups,
)
from app.utils.responses import render

router = APIRouter()
logger = logging.getLogger(__name__)
VALID_ROLES = {"student", "teacher", "admin"}


@router.get("/")
def landing(request: Request):
    return render(request, "home.html", title="Attendance, made clear")


@router.get("/login/{role}")
def login_page(role: str, request: Request):
    if role not in VALID_ROLES:
        return RedirectResponse("/", status_code=303)
    csrf_token(request)
    return render(request, "auth/login.html", role=role, title=f"{role.title()} sign in")


@router.get("/register")
def register_page(request: Request, database: Database = Depends(get_database)):
    csrf_token(request)
    try:
        available = first_admin_setup_available(database)
    except Exception as exc:
        logger.warning("Registration page could not check setup status (%s).", type(exc).__name__)
        available = None
        request.session["flash"] = {
            "kind": "error",
            "message": "Registration is temporarily unavailable. Please try again shortly.",
        }
    return render(
        request,
        "auth/register.html",
        title="Register",
        registration_open=available,
        errors=[],
        form={},
    )


@router.post("/register")
def register(
    request: Request,
    name: str = Form(..., max_length=100),
    email: str = Form(..., max_length=254),
    password: str = Form(..., max_length=128),
    confirm_password: str = Form(..., max_length=128),
    csrf: str = Form(...),
    database: Database = Depends(get_database),
):
    verify_csrf(request, csrf)
    form = {"name": name, "email": email}
    try:
        if not first_admin_setup_available(database):
            return render(
                request,
                "auth/register.html",
                title="Register",
                registration_open=False,
                errors=["Administrator setup has already been completed."],
                form=form,
                status_code=409,
            )
    except Exception as exc:
        logger.warning("Registration could not check setup status (%s).", type(exc).__name__)
        return render(
            request,
            "auth/register.html",
            title="Register",
            registration_open=None,
            errors=[],
            form=form,
            status_code=503,
        )
    try:
        registration = AdminRegistration.model_validate(
            {
                "name": name,
                "email": email,
                "password": password,
                "confirm_password": confirm_password,
            }
        )
    except ValidationError as exc:
        errors = [error["msg"] for error in exc.errors()]
        return render(
            request,
            "auth/register.html",
            title="Register",
            registration_open=True,
            errors=errors,
            form=form,
            status_code=422,
        )

    try:
        create_first_admin(database, registration.name, str(registration.email), registration.password, "web")
    except BootstrapAlreadyComplete:
        return render(
            request,
            "auth/register.html",
            title="Register",
            registration_open=False,
            errors=["Administrator setup has already been completed."],
            form=form,
            status_code=409,
        )
    except EmailAlreadyRegistered:
        return render(
            request,
            "auth/register.html",
            title="Register",
            registration_open=True,
            errors=["An account already uses that email address."],
            form=form,
            status_code=409,
        )
    except Exception as exc:
        logger.warning("Administrator registration failed (%s).", type(exc).__name__)
        return render(
            request,
            "auth/register.html",
            title="Register",
            registration_open=True,
            errors=["Registration is temporarily unavailable. Please try again shortly."],
            form=form,
            status_code=503,
        )

    request.session["flash"] = {"kind": "success", "message": "Administrator account created. You can sign in now."}
    return RedirectResponse("/login/admin", status_code=303)


def _role_signup_page(request: Request, role: str, database: Database, form: dict, errors: list[str], status_code: int = 200):
    groups = subject_groups(database)
    departments = sorted({group["department"] for group in groups}, key=str.casefold)
    return render(
        request,
        "auth/role_register.html",
        title=f"Register as {role}",
        role=role,
        groups=groups,
        departments=departments,
        registration_ready=bool(groups),
        form=form,
        errors=errors,
        status_code=status_code,
    )


@router.get("/register/{role}")
def role_register_page(role: str, request: Request, database: Database = Depends(get_database)):
    if role not in {"student", "teacher"}:
        return RedirectResponse("/register", status_code=303)
    csrf_token(request)
    try:
        if first_admin_setup_available(database):
            request.session["flash"] = {"kind": "error", "message": "Set up the first administrator before registering."}
            return RedirectResponse("/register", status_code=303)
        return _role_signup_page(request, role, database, {}, [])
    except Exception as exc:
        logger.warning("%s registration page is unavailable (%s).", role, type(exc).__name__)
        return render(
            request,
            "auth/role_register.html",
            title=f"Register as {role}",
            role=role,
            groups=[],
            departments=[],
            registration_ready=False,
            form={},
            errors=["Registration is temporarily unavailable. Please try again shortly."],
            status_code=503,
        )


def _signup_error_page(request: Request, role: str, database: Database, form: dict, error: str, status_code: int):
    try:
        return _role_signup_page(request, role, database, form, [error], status_code)
    except Exception as exc:
        logger.warning("Could not reload the %s registration catalog (%s).", role, type(exc).__name__)
        return render(
            request,
            "auth/role_register.html",
            title=f"Register as {role}",
            role=role,
            groups=[],
            departments=[],
            registration_ready=False,
            form=form,
            errors=["Registration is temporarily unavailable. Please try again shortly."],
            status_code=503,
        )


@router.post("/register/student")
def register_student(
    request: Request,
    name: str = Form(..., max_length=120),
    email: str = Form(..., max_length=254),
    password: str = Form(..., max_length=128),
    confirm_password: str = Form(..., max_length=128),
    usn: str = Form(..., max_length=32),
    branch: str = Form(..., max_length=100),
    group_id: str = Form(..., max_length=24),
    subject_ids: list[str] = Form(default=[]),
    csrf: str = Form(...),
    database: Database = Depends(get_database),
):
    verify_csrf(request, csrf)
    form = {"name": name, "email": email, "usn": usn, "branch": branch, "group_id": group_id, "subject_ids": subject_ids}
    try:
        signup = StudentSignup.model_validate({**form, "password": password, "confirm_password": confirm_password})
        create_student_signup(database, signup)
    except ValidationError as exc:
        return _signup_error_page(request, "student", database, form, "; ".join(error["msg"] for error in exc.errors()), 422)
    except AdminSetupRequired:
        request.session["flash"] = {"kind": "error", "message": "Set up the first administrator before registering."}
        return RedirectResponse("/register", status_code=303)
    except CurriculumUnavailable:
        return _signup_error_page(request, "student", database, form, "That semester or subject list changed. Please choose again.", 409)
    except SignupAlreadyExists:
        return _signup_error_page(request, "student", database, form, "That email address or USN is already registered.", 409)
    except Exception as exc:
        logger.warning("Student registration failed (%s).", type(exc).__name__)
        return _signup_error_page(request, "student", database, form, "Registration is temporarily unavailable. Please try again.", 503)
    request.session["flash"] = {"kind": "success", "message": "Your student account is ready. Sign in to view your subjects."}
    return RedirectResponse("/login/student", status_code=303)


@router.post("/register/teacher")
def register_teacher(
    request: Request,
    name: str = Form(..., max_length=120),
    email: str = Form(..., max_length=254),
    password: str = Form(..., max_length=128),
    confirm_password: str = Form(..., max_length=128),
    department: str = Form(..., max_length=100),
    subject_ids: list[str] = Form(default=[]),
    csrf: str = Form(...),
    database: Database = Depends(get_database),
):
    verify_csrf(request, csrf)
    form = {"name": name, "email": email, "department": department, "subject_ids": subject_ids}
    try:
        signup = TeacherSignup.model_validate({**form, "password": password, "confirm_password": confirm_password})
        create_teacher_signup(database, signup)
    except ValidationError as exc:
        return _signup_error_page(request, "teacher", database, form, "; ".join(error["msg"] for error in exc.errors()), 422)
    except AdminSetupRequired:
        request.session["flash"] = {"kind": "error", "message": "Set up the first administrator before registering."}
        return RedirectResponse("/register", status_code=303)
    except CurriculumUnavailable:
        return _signup_error_page(request, "teacher", database, form, "Choose active subjects from your department.", 409)
    except SignupAlreadyExists:
        return _signup_error_page(request, "teacher", database, form, "That email address is already registered.", 409)
    except Exception as exc:
        logger.warning("Teacher registration failed (%s).", type(exc).__name__)
        return _signup_error_page(request, "teacher", database, form, "Registration is temporarily unavailable. Please try again.", 503)
    request.session["flash"] = {"kind": "success", "message": "Your teacher account and subject assignments are ready."}
    return RedirectResponse("/login/teacher", status_code=303)


@router.post("/login/{role}")
def login(
    role: str,
    request: Request,
    identifier: str = Form(..., min_length=3, max_length=254),
    password: str = Form(..., min_length=1, max_length=128),
    csrf: str = Form(...),
    database: Database = Depends(get_database),
):
    if role not in VALID_ROLES:
        return RedirectResponse("/", status_code=303)
    verify_csrf(request, csrf)
    credentials = LoginCredentials.model_validate({"identifier": identifier, "password": password})
    remote_ip = request.client.host if request.client else "unknown"
    try:
        user = authenticate(database, role, credentials.identifier, credentials.password, remote_ip)
    except Exception as exc:
        logger.warning("Sign-in failed because the account store is unavailable (%s).", type(exc).__name__)
        request.session["flash"] = {"kind": "error", "message": "Sign in is temporarily unavailable. Please try again shortly."}
        return RedirectResponse(f"/login/{role}", status_code=303)
    if not user:
        request.session["flash"] = {"kind": "error", "message": "Those sign-in details could not be verified."}
        return RedirectResponse(f"/login/{role}", status_code=303)

    request.session.clear()
    request.session["user_id"] = str(user["_id"])
    request.session["user_summary"] = {"name": user.get("name", ""), "role": user["role"]}
    request.session["csrf_token"] = csrf_token(request)
    request.session["signed_in_at"] = datetime.now(timezone.utc).isoformat()
    return RedirectResponse({"student": "/student", "teacher": "/teacher", "admin": "/admin"}[role], status_code=303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    verify_csrf(request, csrf)
    request.session.clear()
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("attendease_session", httponly=True, samesite="lax")
    return response
