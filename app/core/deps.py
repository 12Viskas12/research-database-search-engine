from fastapi import Depends, HTTPException, Request

from app.services import auth_service

COOKIE = "sid"


async def current_user(request: Request):
    user = await auth_service.user_by_session(request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Login required")
    return user


async def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return user
