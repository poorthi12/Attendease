from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.security.sessions import csrf_token

ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.globals["csrf_token"] = csrf_token


def render(request: Request, template: str, **context):
    status_code = context.pop("status_code", 200)
    context.setdefault("flash", request.session.pop("flash", None))
    context.setdefault("current_user", request.session.get("user_summary"))
    return templates.TemplateResponse(request=request, name=template, context=context, status_code=status_code)
