# -*- coding: utf-8 -*-
"""Authentication endpoints for Web admin login."""

from __future__ import annotations

import logging
import os

import secrets as _secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from api.deps import get_system_config_service
from src.auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE_HOURS_DEFAULT,
    authenticate_user,
    bootstrap_admin_user,
    change_password,
    check_rate_limit,
    clear_rate_limit,
    create_session,
    get_client_ip,
    has_stored_password,
    hash_password,
    is_auth_enabled,
    is_password_changeable,
    is_password_set,
    record_login_failure,
    refresh_auth_state,
    rotate_session_secret,
    set_initial_password,
    validate_password,
    verify_password,
    verify_password_string,
    verify_stored_password,
    verify_session,
)
from src.config import Config, setup_env
from src.storage import get_db
from src.core.config_manager import ConfigManager

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    """Login request body. For first-time setup use password + password_confirm."""

    model_config = {"populate_by_name": True}

    username: str = Field(default="", description="Username (defaults to 'admin' when empty)")
    password: str = Field(default="", description="Password")
    password_confirm: str | None = Field(default=None, alias="passwordConfirm", description="Confirm (first-time)")


class ChangePasswordRequest(BaseModel):
    """Change password request body."""

    model_config = {"populate_by_name": True}

    current_password: str = Field(default="", alias="currentPassword")
    new_password: str = Field(default="", alias="newPassword")
    new_password_confirm: str = Field(default="", alias="newPasswordConfirm")


class AuthSettingsRequest(BaseModel):
    """Update auth enablement and initial password settings."""

    model_config = {"populate_by_name": True}

    auth_enabled: bool = Field(alias="authEnabled")
    password: str = Field(default="")
    password_confirm: str | None = Field(default=None, alias="passwordConfirm")
    current_password: str = Field(default="", alias="currentPassword")


def _cookie_params(request: Request) -> dict:
    """Build cookie params including Secure based on request."""
    secure = False
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        proto = request.headers.get("X-Forwarded-Proto", "").lower()
        secure = proto == "https"
    else:
        # Check URL scheme when not behind proxy
        secure = request.url.scheme == "https"

    try:
        max_age_hours = int(os.getenv("ADMIN_SESSION_MAX_AGE_HOURS", str(SESSION_MAX_AGE_HOURS_DEFAULT)))
    except ValueError:
        max_age_hours = SESSION_MAX_AGE_HOURS_DEFAULT
    max_age = max_age_hours * 3600

    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
        "max_age": max_age,
    }


def _apply_auth_enabled(enabled: bool, request: Request | None = None) -> bool:
    """Persist auth toggle to .env and reload runtime config."""
    manager_applied = False
    if request is not None:
        try:
            service = get_system_config_service(request)
            service.apply_simple_updates(
                updates=[("ADMIN_AUTH_ENABLED", "true" if enabled else "false")],
                mask_token="******",
            )
            manager_applied = True
        except Exception as exc:
            logger.warning(
                "Failed to apply auth toggle via shared SystemConfigService, falling back: %s",
                exc,
                exc_info=True,
            )
            manager_applied = False

    if not manager_applied:
        try:
            manager = ConfigManager()
            manager.apply_updates(
                updates=[("ADMIN_AUTH_ENABLED", "true" if enabled else "false")],
                sensitive_keys=set(),
                mask_token="******",
            )
            manager_applied = True
        except Exception as exc:
            logger.error("Failed to apply auth toggle via ConfigManager: %s", exc, exc_info=True)
            manager_applied = False

    if not manager_applied:
        return False

    Config.reset_instance()
    setup_env(override=True)
    refresh_auth_state()
    return True


def _password_set_for_response(auth_enabled: bool) -> bool:
    """Avoid exposing stored-password state when auth is disabled."""
    return is_password_set() if auth_enabled else False


def _public_user(user: dict | None) -> dict | None:
    """Shape a user dict for the frontend (id/name/admin only)."""
    if not user:
        return None
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "isAdmin": bool(user.get("is_admin")),
    }


def _set_session_cookie(response: Response, session_value: str, request: Request) -> None:
    """Attach the admin session cookie to a response."""
    params = _cookie_params(request)
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_value,
        httponly=params["httponly"],
        samesite=params["samesite"],
        secure=params["secure"],
        path=params["path"],
        max_age=params["max_age"],
    )


@router.get(
    "/status",
    summary="Get auth status",
    description="Returns whether auth is enabled and if the current request is logged in.",
)
async def auth_status(request: Request):
    """Return authEnabled, loggedIn, passwordSet, passwordChangeable without requiring auth."""
    auth_enabled = is_auth_enabled()
    logged_in = False
    current_user = None
    if auth_enabled:
        cookie_val = request.cookies.get(COOKIE_NAME)
        user_id = verify_session(cookie_val) if cookie_val else None
        logged_in = bool(user_id)
        if user_id:
            user = get_db().get_user_by_id(user_id)
            if user and user.get("is_active"):
                current_user = _public_user(user)
            else:
                logged_in = False
    return {
        "authEnabled": auth_enabled,
        "loggedIn": logged_in,
        "passwordSet": _password_set_for_response(auth_enabled),
        "passwordChangeable": is_password_changeable() if auth_enabled else False,
        "currentUser": current_user,
    }


@router.post(
    "/settings",
    summary="Update auth settings",
    description=(
        "Enable or disable password login. When enabling without an existing password, "
        "password + passwordConfirm are required. When re-enabling with a stored password, "
        "currentPassword is required."
    ),
)
async def auth_update_settings(request: Request, body: AuthSettingsRequest):
    """Manage auth enablement from the settings page."""
    target_enabled = body.auth_enabled
    current_enabled = is_auth_enabled()
    stored_password_exists = has_stored_password()

    password = (body.password or "").strip()
    confirm = (body.password_confirm or "").strip()
    current_password = (body.current_password or "").strip()

    if target_enabled:
        if password or confirm:
            if stored_password_exists:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "password_already_set",
                        "message": "已存在管理员密码，请启用认证后通过修改密码功能更新",
                    },
                )
            if not password:
                return JSONResponse(
                    status_code=400,
                    content={"error": "password_required", "message": "请输入要设置的管理员密码"},
                )
            if password != confirm:
                return JSONResponse(
                    status_code=400,
                    content={"error": "password_mismatch", "message": "两次输入的密码不一致"},
                )
            if has_stored_password():
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "password_already_set",
                        "message": "已存在管理员密码，请启用认证后通过修改密码功能更新",
                    },
                )
            err = set_initial_password(password)
            if err:
                return JSONResponse(
                    status_code=400,
                    content={"error": "invalid_password", "message": err},
                )
        elif not stored_password_exists:
            return JSONResponse(
                status_code=400,
                content={"error": "password_required", "message": "开启密码登录前请先设置密码"},
            )
        else:
            # P1 Vulnerability Fix: Enforce current-password check independent of global cached flag
            # We must verify they actually possess a valid admin session, otherwise an attacker
            # could hit a race condition when auth becomes enabled mid-flight.
            # This triggers whenever trying to enable/keep enabled an existing auth setup.
            cookie_val = request.cookies.get(COOKIE_NAME)
            # if target_enabled is True here, they are requesting to enable or keep auth enabled
            is_valid_session = cookie_val and verify_session(cookie_val)
            
            if not is_valid_session:
                if not current_password:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "current_required", "message": "重新开启认证前请输入当前密码"},
                    )
                ip = get_client_ip(request)
                if not check_rate_limit(ip):
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "rate_limited",
                            "message": "Too many failed attempts. Please try again later.",
                        },
                    )
                if not verify_stored_password(current_password):
                    record_login_failure(ip)
                    return JSONResponse(
                        status_code=401,
                        content={"error": "invalid_password", "message": "当前密码错误"},
                    )
                clear_rate_limit(ip)
    else:
        if current_enabled:
            cookie_val = request.cookies.get(COOKIE_NAME)
            is_valid_session = cookie_val and verify_session(cookie_val)

            if not is_valid_session:
                if not current_password:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "current_required", "message": "关闭认证前请输入当前密码"},
                    )
                ip = get_client_ip(request)
                if not check_rate_limit(ip):
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "rate_limited",
                            "message": "Too many failed attempts. Please try again later.",
                        },
                    )
                if not verify_stored_password(current_password):
                    record_login_failure(ip)
                    return JSONResponse(
                        status_code=401,
                        content={"error": "invalid_password", "message": "当前密码错误"},
                    )
                clear_rate_limit(ip)

    if target_enabled != current_enabled:
        if not _apply_auth_enabled(target_enabled, request=request):
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to update auth settings"},
            )
        if not rotate_session_secret():
            rollback_ok = _apply_auth_enabled(current_enabled, request=request)
            if not rollback_ok:
                logger.error("Failed to roll back auth state after session secret rotation failure")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to rotate session secret"},
            )
    else:
        if not _apply_auth_enabled(target_enabled, request=request):
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to update auth settings"},
            )

    if target_enabled:
        # Bind the session to the (bootstrapped) admin user so multi-user
        # endpoints get a valid user_id from the toggle-created session.
        admin_uid = bootstrap_admin_user() or ""
        session_val = create_session(admin_uid)
        if not session_val:
            rollback_ok = _apply_auth_enabled(current_enabled, request=request)
            if not rollback_ok:
                logger.error("Failed to roll back auth state after session creation failure")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to create session"},
            )
        resp = JSONResponse(
            content={
                "authEnabled": True,
                "loggedIn": True,
                "passwordSet": _password_set_for_response(True),
                "passwordChangeable": True,
            }
        )
        _set_session_cookie(resp, session_val, request)
        return resp

    resp = JSONResponse(
        content={
            "authEnabled": False,
            "loggedIn": False,
            "passwordSet": _password_set_for_response(False),
            "passwordChangeable": False,
        }
    )
    resp.delete_cookie(key=COOKIE_NAME, path="/")
    return resp


@router.post(
    "/login",
    summary="Login or set initial password",
    description="Verify password and set session cookie. If password not set yet, accepts password+passwordConfirm.",
)
async def auth_login(request: Request, body: LoginRequest):
    """Verify password or set initial password, set cookie on success. Returns 401 or 429 on failure."""
    if not is_auth_enabled():
        return JSONResponse(
            status_code=400,
            content={"error": "auth_disabled", "message": "Authentication is not configured"},
        )

    password = (body.password or "").strip()
    if not password:
        return JSONResponse(
            status_code=400,
            content={"error": "password_required", "message": "请输入密码"},
        )

    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "message": "Too many failed attempts. Please try again later.",
            },
        )

    db = get_db()
    # Adopt any legacy file-based admin password into a users-table admin row.
    bootstrap_admin_user()
    username = (body.username or "").strip() or "admin"

    # First-time setup: no users exist yet. Only the implicit admin account can
    # be created this way (no open self-registration); subsequent users come
    # from the admin user-management API.
    if db.count_users() == 0:
        if username != "admin":
            record_login_failure(ip)
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_credentials", "message": "用户名或密码错误"},
            )
        confirm = (body.password_confirm or "").strip()
        if password != confirm:
            record_login_failure(ip)
            return JSONResponse(
                status_code=400,
                content={"error": "password_mismatch", "message": "两次输入的密码不一致"},
            )
        err = validate_password(password)
        if err:
            record_login_failure(ip)
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_password", "message": err},
            )
        created = db.create_user(username="admin", password_hash=hash_password(password), is_admin=True)
        if not created:
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Failed to create admin user"},
            )
        uid = created["id"]
        user = created
    else:
        user = authenticate_user(username, password)
        if not user:
            record_login_failure(ip)
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_credentials", "message": "用户名或密码错误"},
            )
        uid = user["id"]

    clear_rate_limit(ip)
    session_val = create_session(uid)
    if not session_val:
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Failed to create session"},
        )

    resp = JSONResponse(content={"ok": True, "user": _public_user(user)})
    _set_session_cookie(resp, session_val, request)
    return resp


def _resolve_session_user_id(request: Request) -> str | None:
    """Resolve the acting user id: middleware state → cookie → bootstrap admin."""
    state = getattr(request, "state", None)
    uid = getattr(state, "user_id", None) if state is not None else None
    if uid:
        return uid
    cookie_val = request.cookies.get(COOKIE_NAME) if hasattr(request, "cookies") else None
    uid = verify_session(cookie_val) if cookie_val else None
    if uid:
        return uid
    # Single-admin fallback (legacy/CLI-style callers without a session).
    return bootstrap_admin_user()


@router.post(
    "/change-password",
    summary="Change password",
    description="Change the current user's password. Requires valid session.",
)
async def auth_change_password(request: Request, body: ChangePasswordRequest):
    """Change the logged-in user's password against the users table."""
    if not is_password_changeable():
        return JSONResponse(
            status_code=400,
            content={"error": "not_changeable", "message": "Password cannot be changed via web"},
        )

    current = (body.current_password or "").strip()
    new_pwd = (body.new_password or "").strip()
    new_confirm = (body.new_password_confirm or "").strip()

    if not current:
        return JSONResponse(
            status_code=400,
            content={"error": "current_required", "message": "请输入当前密码"},
        )
    if new_pwd != new_confirm:
        return JSONResponse(
            status_code=400,
            content={"error": "password_mismatch", "message": "两次输入的新密码不一致"},
        )
    err = validate_password(new_pwd)
    if err:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_password", "message": err},
        )

    uid = _resolve_session_user_id(request)
    db = get_db()
    if not uid or not db.get_user_by_id(uid):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "请先登录"},
        )
    if not verify_password_string(current, db.get_user_password_hash(uid)):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_password", "message": "当前密码错误"},
        )
    db.set_user_password(uid, hash_password(new_pwd))
    return Response(status_code=204)


@router.post(
    "/logout",
    summary="Logout",
    description="Clear session cookie.",
)
async def auth_logout(request: Request):
    """Clear session cookie."""
    resp = Response(status_code=204)
    resp.delete_cookie(key=COOKIE_NAME, path="/")
    return resp


# ----------------------------------------------------------------------
# Google OAuth (login only — accounts must be pre-created by an admin)
# ----------------------------------------------------------------------

OAUTH_STATE_COOKIE = "dsa_oauth_state"


def _google_oauth_config(request: Request) -> tuple[str, str, str]:
    """Return (client_id, client_secret, redirect_uri). Empty id/secret == unconfigured."""
    cid = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    redirect = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()
    if not redirect:
        redirect = str(request.base_url).rstrip("/") + "/api/v1/auth/google/callback"
    return cid, secret, redirect


@router.get("/google/login", summary="Start Google OAuth login")
async def google_login(request: Request):
    """Redirect to Google's consent screen. Account must already exist."""
    if not is_auth_enabled():
        return JSONResponse(status_code=400, content={"error": "auth_disabled", "message": "Authentication is not configured"})
    cid, secret, redirect = _google_oauth_config(request)
    if not cid or not secret:
        return JSONResponse(status_code=400, content={"error": "google_not_configured", "message": "未配置 Google 登入"})

    state = _secrets.token_urlsafe(24)
    params = {
        "client_id": cid,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
    resp.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=_cookie_params(request)["secure"],
        path="/",
    )
    return resp


@router.get("/google/callback", summary="Google OAuth callback")
async def google_callback(request: Request, code: str = "", state: str = ""):
    """Exchange the code, match to a pre-created user, and issue a session."""
    if not is_auth_enabled():
        return RedirectResponse("/login")
    saved = request.cookies.get(OAUTH_STATE_COOKIE)
    if not code or not state or not saved or not _secrets.compare_digest(state, saved):
        return RedirectResponse("/login?error=google_state")

    cid, secret, redirect = _google_oauth_config(request)
    if not cid or not secret:
        return RedirectResponse("/login?error=google_not_configured")

    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": cid,
                    "client_secret": secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect,
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise ValueError("no access_token")
            info = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            info.raise_for_status()
            userinfo = info.json()
    except Exception as exc:
        logger.warning("Google OAuth exchange failed: %s", exc)
        return RedirectResponse("/login?error=google_failed")

    sub = userinfo.get("sub")
    email = userinfo.get("email")
    if not sub:
        return RedirectResponse("/login?error=google_failed")

    db = get_db()
    user = db.get_user_by_google_sub(sub)
    if not user and email:
        candidate = db.get_user_by_email(email)
        if candidate:
            db.link_google_to_user(candidate["id"], sub, email)
            user = db.get_user_by_id(candidate["id"])
    if not user or not user.get("is_active"):
        # Admin-only account creation: an unrecognised Google identity is rejected.
        return RedirectResponse("/login?error=google_not_authorized")

    session_val = create_session(user["id"])
    if not session_val:
        return RedirectResponse("/login?error=google_failed")
    resp = RedirectResponse("/")
    _set_session_cookie(resp, session_val, request)
    resp.delete_cookie(key=OAUTH_STATE_COOKIE, path="/")
    return resp
