"""Opaque device tokens. Refresh reuse revokes the entire device family."""
import asyncio
import json
import secrets
import time
from sqlalchemy import select, insert, update, and_
from starlette.requests import Request
from starlette.responses import JSONResponse
from backend.auth import AuthError, _token_hash, account_context
from backend.data_paths import workspace
from backend.identity import current_identity
from backend.storage import models as m
from backend.storage.repository import uid, rowdict
from backend.storage.database import repository_context


class DeviceTokens:
    access_ttl = 15 * 60
    refresh_ttl = 30 * 86400

    def __init__(self, database, store, clock=time.time):
        self.db, self.store, self.clock = database, store, clock

    def _issue(self, c, user_id, device_name, family_id=None, expires=None):
        now = self.clock()
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        values = dict(id=uid(), family_id=family_id or uid(), user_id=user_id, device_name=device_name[:128],
                      access_hash=_token_hash(access), refresh_hash=_token_hash(refresh), access_expires_at=now + self.access_ttl,
                      refresh_expires_at=expires or now + self.refresh_ttl, created_at=now, rotated=False, revoked=False)
        c.execute(insert(m.native_sessions).values(**values))
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.access_ttl,
                "refresh_expires_at": values["refresh_expires_at"], "device_session_id": values["family_id"]}

    def login(self, login, password, client, device_name):
        cookie, user, _ = self.store.login(login, password, client)
        self.store.logout(cookie)
        with self.db.transaction() as c:
            tokens = self._issue(c, user["id"], device_name)
        return {**tokens, "user": user}

    def issue_for_user(self, user, device_name):
        with self.db.transaction() as c:
            return {**self._issue(c, user["id"], device_name), "user": user}

    def refresh(self, token):
        if not isinstance(token, str) or len(token) > 128:
            raise AuthError("invalid_refresh", "请重新登录", 401)
        error, result = None, None
        with self.db.transaction() as c:
            old = rowdict(c.execute(select(m.native_sessions).where(m.native_sessions.c.refresh_hash == _token_hash(token)).with_for_update()).first())
            if not old or old["revoked"] or old["refresh_expires_at"] <= self.clock():
                error = AuthError("invalid_refresh", "登录已过期，请重新登录", 401)
            elif old["rotated"]:
                c.execute(update(m.native_sessions).where(m.native_sessions.c.family_id == old["family_id"]).values(revoked=True))
                error = AuthError("refresh_reused", "设备会话已撤销，请重新登录", 401)
            else:
                user = rowdict(c.execute(select(m.users).where(m.users.c.id == old["user_id"], m.users.c.disabled == 0)).first())
                if not user:
                    error = AuthError("auth_required", "请重新登录", 401)
                else:
                    c.execute(update(m.native_sessions).where(m.native_sessions.c.id == old["id"]).values(rotated=True))
                    result = {**self._issue(c, old["user_id"], old["device_name"], old["family_id"], old["refresh_expires_at"]), "user": self.store.public_user(user)}
        if error:
            raise error
        return result

    def resolve(self, token):
        if not token or len(token) > 128:
            return None
        with self.db.transaction() as c:
            row = c.execute(select(m.users).join(m.native_sessions, m.native_sessions.c.user_id == m.users.c.id).where(
                m.native_sessions.c.access_hash == _token_hash(token), m.native_sessions.c.access_expires_at > self.clock(),
                m.native_sessions.c.rotated.is_(False), m.native_sessions.c.revoked.is_(False), m.users.c.disabled == 0)).first()
            return self.store.public_user(row._mapping) if row else None

    def sessions(self):
        with self.db.transaction() as c:
            return [dict(id=r.family_id, device_name=r.device_name, created_at=r.created_at, expires_at=r.refresh_expires_at)
                    for r in c.execute(select(m.native_sessions).where(m.native_sessions.c.user_id == current_identity()["id"],
                        m.native_sessions.c.rotated.is_(False), m.native_sessions.c.revoked.is_(False), m.native_sessions.c.refresh_expires_at > self.clock()))]

    def revoke(self, family_id):
        with self.db.transaction() as c:
            c.execute(update(m.native_sessions).where(m.native_sessions.c.family_id == family_id,
                m.native_sessions.c.user_id == current_identity()["id"]).values(revoked=True))


class NativeGateway:
    """Only verified Bearer requests bypass browser Origin/CSRF enforcement."""
    def __init__(self, browser, core, store, repository, tokens):
        self.browser, self.core, self.store, self.repo, self.tokens = browser, core, store, repository, tokens

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            with repository_context(self.repo):
                return await self.browser(scope, receive, send)
        request = Request(scope, receive)
        path = request.url.path
        try:
            if path in ("/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/register", "/api/v1/auth/email-code"):
                if request.method != "POST":
                    raise AuthError("method_not_allowed", "请求方法不支持", 405)
                # Browser requests must keep Origin checks even on token routes.
                if request.headers.get("origin") or request.headers.get("sec-fetch-site"):
                    self.browser.require_origin(request)
                data = await self.browser.payload(request)
                client = request.client.host if request.client else "unknown"
                name = data.get("device_name", "Apple 客户端")
                if not isinstance(name, str) or not 1 <= len(name) <= 128:
                    raise AuthError("invalid_device", "设备名称无效")
                if path.endswith("/refresh"):
                    result = await asyncio.to_thread(self.tokens.refresh, data.get("refresh_token"))
                elif path.endswith("/login"):
                    result = await asyncio.to_thread(self.tokens.login, data.get("login"), data.get("password"), client, name)
                elif path.endswith("/email-code"):
                    result = await asyncio.to_thread(self.store.send_email_code, data.get("email"), client)
                else:
                    cookie, user, _ = await asyncio.to_thread(self.store.register, data.get("username"), data.get("email"), data.get("code"), data.get("password"), data.get("api_key"), client)
                    await asyncio.to_thread(self.store.logout, cookie)
                    result = await asyncio.to_thread(self.tokens.issue_for_user, user, name)
                await JSONResponse(result, headers={"Cache-Control": "no-store"})(scope, receive, send)
                return
            header = request.headers.get("authorization", "")
            if path.startswith("/api/v1/") and header:
                if not header.startswith("Bearer "):
                    raise AuthError("invalid_access", "请重新登录", 401)
                user = await asyncio.to_thread(self.tokens.resolve, header[7:])
                if not user:
                    raise AuthError("invalid_access", "请重新登录", 401)
                directory = await asyncio.to_thread(self.store.prepare_workspace, user)
                with repository_context(self.repo), account_context(self.store, user), workspace(directory):
                    return await self.core(scope, receive, send)
            with repository_context(self.repo):
                return await self.browser(scope, receive, send)
        except AuthError as exc:
            await JSONResponse({"error": exc.code, "detail": exc.detail}, status_code=exc.status,
                               headers={"Cache-Control": "no-store"})(scope, receive, send)

