from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.deps import admin_user
from app.core.redis_client import get_redis
from app.services import (
    audit_service,
    auth_service,
    backup_service,
    history_service,
    record_service,
    settings_service,
    stats_service,
)

router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_user)])


class RoleBody(BaseModel):
    role: str
    days: int | None = None


class InviteBody(BaseModel):
    role: str = "user"
    note: str | None = None
    days: int | None = None


class PasswordBody(BaseModel):
    password: str | None = None


class BlockBody(BaseModel):
    blocked: bool


class RecordBody(BaseModel):
    data: dict


class HideBody(BaseModel):
    hidden: bool


class RestoreBody(BaseModel):
    name: str


class AutopackBody(BaseModel):
    enabled: bool
    days: int = 7
    method: str = "bz2"


@router.get("/requests")
async def requests():
    return await auth_service.list_requests()


@router.post("/requests/{request_id}/approve")
async def approve(request_id: int, body: RoleBody, admin=Depends(admin_user)):
    invite = await auth_service.approve_request(
        request_id, body.role, admin["id"], body.days
    )
    await audit_service.log(
        admin, "request_approved", request=request_id, role=body.role, days=body.days
    )
    return {"id": invite["id"], "role": invite["role"]}


@router.post("/requests/{request_id}/reject")
async def reject(request_id: int, admin=Depends(admin_user)):
    await auth_service.reject_request(request_id)
    await audit_service.log(admin, "request_rejected", request=request_id)
    return {"ok": True}


@router.get("/invites")
async def invites():
    return await auth_service.list_invites()


@router.post("/invites", status_code=201)
async def create_invite(body: InviteBody, admin=Depends(admin_user)):
    invite = await auth_service.create_invite(
        body.role, body.note, admin["id"], days=body.days
    )
    await audit_service.log(
        admin, "invite_created", role=body.role, days=body.days, invite=invite["id"]
    )
    return invite


@router.delete("/invites/{invite_id}")
async def delete_invite(invite_id: int, admin=Depends(admin_user)):
    await auth_service.delete_invite(invite_id)
    await audit_service.log(admin, "invite_deleted", invite=invite_id)
    return {"ok": True}


@router.get("/users")
async def users():
    return await auth_service.list_users()


@router.patch("/users/{user_id}")
async def set_role(user_id: int, body: RoleBody, admin=Depends(admin_user)):
    await auth_service.set_role(user_id, body.role, admin["id"], body.days)
    await audit_service.log(
        admin, "role_changed", user=user_id, role=body.role, days=body.days
    )
    return {"ok": True}


@router.post("/users/{user_id}/password")
async def reset_password(user_id: int, body: PasswordBody, admin=Depends(admin_user)):
    password = await auth_service.reset_password(user_id, body.password)
    await audit_service.log(admin, "password_reset", user=user_id)
    return {"password": password}


@router.post("/users/{user_id}/block")
async def block_user(user_id: int, body: BlockBody, admin=Depends(admin_user)):
    await auth_service.set_blocked(user_id, body.blocked, admin["id"])
    await audit_service.log(
        admin, "user_blocked" if body.blocked else "user_unblocked", user=user_id
    )
    return {"ok": True}


@router.get("/stats")
async def stats():
    return await stats_service.stats()


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin=Depends(admin_user)):
    await auth_service.delete_user(user_id, admin["id"])
    await audit_service.log(admin, "user_deleted", user=user_id)
    return {"ok": True}


@router.get("/audit")
async def audit(
    before: int | None = None,
    action: str | None = None,
    actor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    return await audit_service.entries(before, action, actor, limit)


@router.get("/audit/actions")
async def audit_actions():
    return await audit_service.actions()


@router.get("/settings")
async def get_settings():
    return {"autopack": await settings_service.autopack()}


@router.put("/settings")
async def put_settings(body: AutopackBody, admin=Depends(admin_user)):
    try:
        value = await settings_service.set_autopack(body.enabled, body.days, body.method)
    except settings_service.SettingsError as e:
        raise auth_service.AuthError(str(e))
    await audit_service.log(admin, "settings_changed", autopack=value)
    return {"autopack": value}


@router.post("/vocab/rebuild", status_code=202)
async def rebuild_vocab():
    redis = await get_redis()
    await redis.enqueue_job("rebuild_vocab")
    return {"status": "queued"}


@router.patch("/records/{record_id}")
async def edit_record(record_id: str, body: RecordBody, admin=Depends(admin_user)):
    await record_service.edit(admin, record_id, body.data)
    return {"ok": True}


@router.post("/records/{record_id}/hide")
async def hide_record(record_id: str, body: HideBody, admin=Depends(admin_user)):
    await record_service.hide(admin, record_id, body.hidden)
    return {"ok": True}


@router.delete("/records/{record_id}")
async def delete_record(record_id: str, admin=Depends(admin_user)):
    await record_service.delete(admin, record_id)
    return {"ok": True}


@router.get("/missed")
async def missed():
    return await history_service.missed_top()


@router.delete("/missed")
async def clear_missed(admin=Depends(admin_user)):
    await history_service.missed_clear()
    await audit_service.log(admin, "missed_cleared")
    return {"ok": True}


@router.get("/backups")
async def backups():
    return backup_service.listing()


@router.post("/backups", status_code=202)
async def create_backup(admin=Depends(admin_user)):
    backup_service.request_backup()
    await audit_service.log(admin, "backup_requested")
    return {"status": "queued"}


@router.post("/backups/restore", status_code=202)
async def restore_backup(body: RestoreBody, admin=Depends(admin_user)):
    backup_service.request_restore(body.name)
    await audit_service.log(admin, "backup_restore_requested", file=body.name)
    return {"status": "queued"}


@router.get("/backups/{name}")
async def download_backup(name: str, admin=Depends(admin_user)):
    path = backup_service.valid_name(name)
    await audit_service.log(admin, "backup_downloaded", file=name)
    return FileResponse(path, filename=name, media_type="application/gzip")
