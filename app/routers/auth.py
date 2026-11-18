from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import COOKIE, current_user
from app.services import auth_service

router = APIRouter(prefix="/api/auth")


class RegisterBody(BaseModel):
    token: str
    username: str
    password: str


class LoginBody(BaseModel):
    username: str
    password: str


def set_cookie(response, session):
    response.set_cookie(
        COOKIE,
        session,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/register", status_code=201)
async def register(body: RegisterBody, response: Response):
    user, session = await auth_service.register(body.token, body.username, body.password)
    set_cookie(response, session)
    return user


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else ""
    user, session = await auth_service.login(body.username, body.password, ip)
    set_cookie(response, session)
    return user


@router.post("/logout")
async def logout(request: Request, response: Response):
    await auth_service.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user=Depends(current_user)):
    return await auth_service.profile(user)
