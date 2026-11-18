from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import admin_user
from app.services import auth_service

router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_user)])


class RoleBody(BaseModel):
    role: str


class InviteBody(BaseModel):
    role: str = "user"
    note: str | None = None


@router.get("/requests")
async def requests():
    return await auth_service.list_requests()


@router.post("/requests/{request_id}/approve")
async def approve(request_id: int, body: RoleBody, admin=Depends(admin_user)):
    invite = await auth_service.approve_request(request_id, body.role, admin["id"])
    return {"id": invite["id"], "role": invite["role"]}


@router.post("/requests/{request_id}/reject")
async def reject(request_id: int):
    await auth_service.reject_request(request_id)
    return {"ok": True}


@router.get("/invites")
async def invites():
    return await auth_service.list_invites()


@router.post("/invites", status_code=201)
async def create_invite(body: InviteBody, admin=Depends(admin_user)):
    return await auth_service.create_invite(body.role, body.note, admin["id"])


@router.delete("/invites/{invite_id}")
async def delete_invite(invite_id: int):
    await auth_service.delete_invite(invite_id)
    return {"ok": True}


@router.get("/users")
async def users():
    return await auth_service.list_users()


@router.patch("/users/{user_id}")
async def set_role(user_id: int, body: RoleBody, admin=Depends(admin_user)):
    await auth_service.set_role(user_id, body.role, admin["id"])
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin=Depends(admin_user)):
    await auth_service.delete_user(user_id, admin["id"])
    return {"ok": True}
