from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import COOKIE, current_user
from app.services import audit_service, auth_service

router = APIRouter(prefix="/api/auth")


class RegisterBody(BaseModel):
    token: str
    username: str
    password: str


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


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


def client_ip(request):
    return request.client.host if request.client else ""


@router.post("/register", status_code=201)
async def register(body: RegisterBody, request: Request, response: Response):
    user, session = await auth_service.register(body.token, body.username, body.password)
    set_cookie(response, session)
    await audit_service.log(user, "register", role=user["role"], ip=client_ip(request))
    return user


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    ip = client_ip(request)
    try:
        user, session = await auth_service.login(body.username, body.password, ip)
    except auth_service.AuthError as e:
        if e.status == 401:
            await audit_service.log(
                None, "login_failed", name=body.username.strip()[:64], ip=ip
            )
        raise
    set_cookie(response, session)
    await audit_service.log(user, "login", ip=ip)
    return user


@router.post("/logout")
async def logout(request: Request, response: Response):
    await auth_service.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user=Depends(current_user)):
    return await auth_service.profile(user)


@router.post("/password")
async def password(body: PasswordBody, request: Request, user=Depends(current_user)):
    await auth_service.change_password(
        user, body.current, body.new, request.cookies.get(COOKIE)
    )
    await audit_service.log(user, "password_changed")
    return {"ok": True}


@router.post("/tg-code")
async def tg_code(user=Depends(current_user)):
    return {"code": await auth_service.link_code(user), "minutes": 10}


@router.delete("/tg")
async def tg_unlink(user=Depends(current_user)):
    await auth_service.unlink_tg(user["id"])
    await audit_service.log(user, "tg_unlinked")
    return {"ok": True}
