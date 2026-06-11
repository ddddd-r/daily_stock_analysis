# -*- coding: utf-8 -*-
"""Admin user-management endpoints.

Accounts are created here by an admin — there is no open self-registration.
All routes require an active admin (see ``require_admin``). When auth is
disabled the instance is single-tenant and these routes are effectively
unused by the UI.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.deps import require_admin
from src.auth import hash_password, validate_password
from src.storage import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateUserRequest(BaseModel):
    model_config = {"populate_by_name": True}

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", description="Initial password (optional for Google-only accounts)")
    email: str | None = Field(default=None)
    is_admin: bool = Field(default=False, alias="isAdmin")


class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=1)


class SetActiveRequest(BaseModel):
    model_config = {"populate_by_name": True}

    is_active: bool = Field(alias="isActive")


@router.get("", summary="List users")
async def list_users(_admin=Depends(require_admin)):
    return {"users": get_db().list_users()}


@router.post("", summary="Create a user")
async def create_user(body: CreateUserRequest, _admin=Depends(require_admin)):
    db = get_db()
    password_hash = None
    auth_provider = "local"
    if body.password:
        err = validate_password(body.password)
        if err:
            return JSONResponse(status_code=400, content={"error": "invalid_password", "message": err})
        password_hash = hash_password(body.password)
    elif body.email:
        # No password but an email — intended for Google login.
        auth_provider = "google"
    else:
        return JSONResponse(
            status_code=400,
            content={"error": "credential_required", "message": "请提供初始密码，或提供 Email 以供 Google 登入"},
        )

    created = db.create_user(
        username=body.username,
        password_hash=password_hash,
        email=body.email,
        is_admin=body.is_admin,
        auth_provider=auth_provider,
    )
    if not created:
        return JSONResponse(
            status_code=409,
            content={"error": "user_exists", "message": "用户名或 Email 已存在"},
        )
    return JSONResponse(status_code=201, content=created)


@router.post("/{user_id}/password", summary="Set a user's password")
async def set_user_password(user_id: str, body: SetPasswordRequest, _admin=Depends(require_admin)):
    err = validate_password(body.password)
    if err:
        return JSONResponse(status_code=400, content={"error": "invalid_password", "message": err})
    if not get_db().set_user_password(user_id, hash_password(body.password)):
        return JSONResponse(status_code=404, content={"error": "not_found", "message": "用户不存在"})
    return {"ok": True}


@router.post("/{user_id}/active", summary="Enable or disable a user")
async def set_user_active(user_id: str, body: SetActiveRequest, admin=Depends(require_admin)):
    # Guard: an admin cannot disable their own account.
    if admin and admin.get("id") == user_id and not body.is_active:
        return JSONResponse(status_code=400, content={"error": "self_disable", "message": "不能停用自己的账号"})
    if not get_db().set_user_active(user_id, body.is_active):
        return JSONResponse(status_code=404, content={"error": "not_found", "message": "用户不存在"})
    return {"ok": True}
