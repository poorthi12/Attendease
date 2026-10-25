from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.security.sessions import get_current_user


def require_role(*roles: str) -> Callable:
    def dependency(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles or not user.get("is_active", True):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this page.")
        return user

    return dependency
