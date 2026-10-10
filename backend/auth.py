"""Persistent accounts, encrypted user credentials and an ASGI account gateway.

The account registry is separate from learning databases. Only the server-side
bootstrap command can create the reserved ``studyadmin`` owner. No guest data or
owner credentials are copied into a new account.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
from email.message import EmailMessage
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend.data_paths import workspace


ROOT = Path(__file__).resolve().parent.parent
OWNER_USERNAME = "studyadmin"
COOKIE = "__Host-study_account"
LOCAL_COOKIE = "study_account_local"
DEEPSEEK_GUIDE_URL = "/deepseek-guide.html"
_STORE = ContextVar("study_account_store", default=None)


class AuthError(Exception):
    def __init__(self, code, detail, status=400):
        self.code, self.detail, self.status = code, detail, status
        super().__init__(detail)


def _email(value):
    if not isinstance(value, str):
        raise AuthError("invalid_email", "请输入有效的邮箱地址。")
    value = value.strip().lower()
    # Restrict recipients to one ASCII address, preventing header injection.
    if len(value) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        raise AuthError("invalid_email", "请输入有效的邮箱地址。")
    return value


def _username(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{2,31}", value):
        raise AuthError("invalid_username", "用户名为 3–32 个字符，以英文字母开头，可含数字、下划线、点和连字符。")
    if value.casefold() == OWNER_USERNAME:
        raise AuthError("reserved_username", "该用户名保留给网站管理员。")
    return value


def _password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        raise AuthError("invalid_password", "密码需为 12–128 个字符。")
    return value


def validate_api_key(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 512 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
        raise AuthError("invalid_api_key", "请输入有效的 DeepSeek API Key（8–512 个字符，不能含空白）。")
    return value


def _password_hash(password):
    salt = secrets.token_bytes(16)
    digest = Scrypt(salt=salt, length=64, n=32768, r=8, p=1).derive(password.encode("utf-8"))
    return "scrypt$32768$8$1$" + salt.hex() + "$" + digest.hex()


def _password_matches(password, encoded):
    try:
        name, n, r, p, salt, expected = encoded.split("$")
        # The work factors are fixed; a corrupt database cannot request huge allocations.
        if (name, n, r, p) != ("scrypt", "32768", "8", "1"):
            return False
        digest = Scrypt(salt=bytes.fromhex(salt), length=64, n=32768, r=8, p=1).derive(password.encode("utf-8"))
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expiry(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class SMTPMailer:
    """A configured, TLS-only SMTP delivery adapter. Disabled by default."""

    def __init__(self, environ=None):
        env = os.environ if environ is None else environ
        self.host = env.get("STUDY_SMTP_HOST", "").strip()
        self.port = int(env.get("STUDY_SMTP_PORT", "465"))
        self.username = env.get("STUDY_SMTP_USERNAME", "")
        self.password = env.get("STUDY_SMTP_PASSWORD", "")
        self.sender = env.get("STUDY_SMTP_FROM", "")
        self.security = env.get("STUDY_SMTP_SECURITY", "ssl").lower()
        if self.security not in ("ssl", "starttls"):
            raise RuntimeError("STUDY_SMTP_SECURITY 必须为 ssl 或 starttls，禁止未加密发送")
        self.enabled = bool(self.host and self.sender and self.username and self.password)
        if self.sender:
            _email(self.sender)

    def send_code(self, email, code):
        if not self.enabled:
            raise RuntimeError("邮件验证未配置")
        msg = EmailMessage()
        msg["Subject"] = "学习账号注册验证码"
        msg["From"], msg["To"] = self.sender, email
        msg.set_content(f"你的注册验证码为：{code}\n\n验证码 5 分钟内有效，请勿告知他人。如非本人申请，请忽略此邮件。")
        context = ssl.create_default_context()
        if self.security == "ssl":
            client = smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=context)
        else:
            client = smtplib.SMTP(self.host, self.port, timeout=15)
        with client:
            if self.security == "starttls":
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            client.login(self.username, self.password)
            client.send_message(msg)


class AccountStore:
    def __init__(self, root, owner_directory, *, encryption_key=None, mailer=None, clock=time.time, session_ttl=7 * 86400):
        self.root = Path(root).expanduser().resolve()
        self.owner_directory = Path(owner_directory).expanduser().resolve()
        if self.root == ROOT or self.root == ROOT.parent or self.root == self.owner_directory:
            raise RuntimeError("账号目录必须独立于项目及主人数据目录")
        key = encryption_key or os.environ.get("STUDY_AUTH_ENCRYPTION_KEY", "")
        if not key:
            raise RuntimeError("启用账号系统前必须配置 STUDY_AUTH_ENCRYPTION_KEY；用 Fernet.generate_key() 生成并安全备份")
        try:
            self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("STUDY_AUTH_ENCRYPTION_KEY 格式无效") from exc
        self.code_secret = hashlib.sha256(key.encode() if isinstance(key, str) else key).digest()
        self.mailer = mailer if mailer is not None else SMTPMailer()
        self.clock, self.session_ttl = clock, session_ttl
        self.db_path = self.root / "accounts.db"
        self._prepared = False
        self._prepare_lock = threading.RLock()
        self._workspace_locks = {}
        self._workspace_initialized = set()
        self._dummy_password = _password_hash(secrets.token_urlsafe(32))

    @property
    def registration_enabled(self):
        return bool(self.mailer.enabled)

    def prepare(self):
        with self._prepare_lock:
            if self._prepared:
                return
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            (self.root / "users").mkdir(exist_ok=True, mode=0o700)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY, username TEXT NOT NULL,
                        username_norm TEXT NOT NULL UNIQUE, email TEXT UNIQUE,
                        password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','user')),
                        api_key_encrypted BLOB, created_at REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS single_owner ON users(role) WHERE role='owner';
                    CREATE TABLE IF NOT EXISTS login_sessions (
                        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                        created_at REAL NOT NULL, expires_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS sessions_user ON login_sessions(user_id);
                    CREATE TABLE IF NOT EXISTS email_challenges (
                        email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at REAL NOT NULL,
                        sent_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                        consumed INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS auth_rate_events (
                        bucket TEXT NOT NULL, created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS rate_bucket ON auth_rate_events(bucket,created_at);
                """)
            os.chmod(self.db_path, 0o600)
            self._prepared = True

    @contextmanager
    def connection(self):
        self.prepare()
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _bucket(self, kind, value):
        # Do not retain raw IPs or failed login identifiers in the rate table.
        return kind + ":" + hmac.new(self.code_secret, str(value).encode(), hashlib.sha256).hexdigest()

    def _limit(self, conn, kind, value, limit, interval):
        now = self.clock()
        bucket = self._bucket(kind, value)
        count = conn.execute("SELECT count(*) FROM auth_rate_events WHERE bucket=? AND created_at>?", (bucket, now - interval)).fetchone()[0]
        if count >= limit:
            return False
        conn.execute("INSERT INTO auth_rate_events VALUES (?,?)", (bucket, now))
        conn.execute("DELETE FROM auth_rate_events WHERE created_at<?", (now - 86400,))
        return True

    def _code_hash(self, email, code):
        return hmac.new(self.code_secret, (email + "\0" + code).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def public_user(row):
        return {"id": row["id"], "username": row["username"], "email": row["email"], "role": row["role"],
                "api_key_configured": bool(row["api_key_encrypted"])}

    def send_email_code(self, email, client):
        email = _email(email)
        if not self.registration_enabled:
            raise AuthError("registration_disabled", "管理员尚未启用邮件验证码注册。", 503)
        code = f"{secrets.randbelow(1000000):06d}"
        send = False
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ip_ok = self._limit(conn, "send-ip", client, 10, 3600)
            email_ok = self._limit(conn, "send-email", email, 5, 3600)
            previous = conn.execute("SELECT sent_at FROM email_challenges WHERE email=?", (email,)).fetchone()
            # Deliver the same generic verification email for existing addresses;
            # SMTP timing must not reveal whether an account already exists.
            if ip_ok and email_ok and (not previous or previous[0] <= self.clock() - 60):
                conn.execute("INSERT INTO email_challenges VALUES (?,?,?,?,0,0) ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash,expires_at=excluded.expires_at,sent_at=excluded.sent_at,attempts=0,consumed=0",
                             (email, self._code_hash(email, code), self.clock() + 300, self.clock()))
                send = True
        if send:
            try:
                self.mailer.send_code(email, code)
            except Exception:
                # Never log the SMTP exception: providers may echo recipients/auth data.
                with self.connection() as conn:
                    conn.execute("UPDATE email_challenges SET consumed=1 WHERE email=? AND code_hash=?", (email, self._code_hash(email, code)))
                raise AuthError("email_unavailable", "邮件服务暂不可用，请稍后重试。", 503)
        # Same response for existing, cooling down and rate-limited addresses.
        return {"sent": True, "message": "如果该邮箱可用于注册，验证码将在几分钟内送达。"}

    def register(self, username, email, code, password, api_key, client):
        if not self.registration_enabled:
            raise AuthError("registration_disabled", "管理员尚未启用邮件验证码注册。", 503)
        username, email = _username(username), _email(email)
        password, api_key = _password(password), validate_api_key(api_key)
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise AuthError("invalid_code", "验证码无效或已过期。")
        # Persist rate consumption and failed attempts before reporting an error.
        error = None
        user_id = secrets.token_hex(16)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._limit(conn, "register-ip", client, 20, 3600):
                error = AuthError("auth_rate_limited", "操作过于频繁，请稍后重试。", 429)
            challenge = conn.execute("SELECT * FROM email_challenges WHERE email=?", (email,)).fetchone()
            if not error and (not challenge or challenge["consumed"] or challenge["expires_at"] <= self.clock() or challenge["attempts"] >= 5):
                error = AuthError("invalid_code", "验证码无效或已过期。")
            if not error and not hmac.compare_digest(challenge["code_hash"], self._code_hash(email, code)):
                conn.execute("UPDATE email_challenges SET attempts=attempts+1,consumed=CASE WHEN attempts+1>=5 THEN 1 ELSE consumed END WHERE email=?", (email,))
                error = AuthError("invalid_code", "验证码无效或已过期。")
            if not error:
                conflict = conn.execute("SELECT 1 FROM users WHERE email=? OR username_norm=?", (email, username.casefold())).fetchone()
                if conflict:
                    error = AuthError("registration_conflict", "无法创建账号，请检查注册信息或直接登录。")
                else:
                    conn.execute("INSERT INTO users VALUES (?,?,?,?,?,'user',?,?,0)",
                                 (user_id, username, username.casefold(), email, _password_hash(password), self.cipher.encrypt(api_key.encode()), self.clock()))
                    conn.execute("UPDATE email_challenges SET consumed=1 WHERE email=?", (email,))
        if error:
            raise error
        return self.create_session(user_id)

    def bootstrap_owner(self, password, *, email=None, api_key=None, replace_password=False):
        """Administrative CLI only; never exposed as an HTTP route."""
        password = _password(password)
        email = _email(email) if email else None
        encrypted = self.cipher.encrypt(validate_api_key(api_key).encode()) if api_key else None
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM users WHERE username_norm=?", (OWNER_USERNAME,)).fetchone()
            if row:
                if not replace_password:
                    raise AuthError("owner_exists", "主人账号已存在；重设密码请显式指定 --reset-password。")
                if row["role"] != "owner" or row["id"] != OWNER_USERNAME:
                    raise RuntimeError("保留主人账号信息不一致，拒绝引导")
                conn.execute("UPDATE users SET password_hash=?,email=COALESCE(?,email),api_key_encrypted=COALESCE(?,api_key_encrypted),disabled=0 WHERE id=?", (_password_hash(password), email, encrypted, OWNER_USERNAME))
                conn.execute("DELETE FROM login_sessions WHERE user_id=?", (OWNER_USERNAME,))
            else:
                conn.execute("INSERT INTO users VALUES (?,?,?,?,?,'owner',?,?,0)",
                             (OWNER_USERNAME, OWNER_USERNAME, OWNER_USERNAME, email, _password_hash(password), encrypted, self.clock()))
        return OWNER_USERNAME

    def login(self, login, password, client):
        if not isinstance(login, str) or len(login) > 254 or not isinstance(password, str) or len(password) > 128:
            raise AuthError("invalid_login", "账号或密码错误。", 401)
        login = login.strip().casefold()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ip_ok = self._limit(conn, "login-ip", client, 30, 900)
            id_ok = self._limit(conn, "login-id", login, 10, 900)
            row = conn.execute("SELECT * FROM users WHERE username_norm=? OR email=?", (login, login)).fetchone()
        if not ip_ok or not id_ok:
            raise AuthError("auth_rate_limited", "登录尝试过于频繁，请 15 分钟后重试。", 429)
        encoded = row["password_hash"] if row else self._dummy_password
        matches = _password_matches(password, encoded)
        if not row or row["disabled"] or not matches:
            raise AuthError("invalid_login", "账号或密码错误。", 401)
        return self.create_session(row["id"])

    def create_session(self, user_id):
        token = secrets.token_urlsafe(32)
        now, expires = self.clock(), self.clock() + self.session_ttl
        with self.connection() as conn:
            conn.execute("DELETE FROM login_sessions WHERE expires_at<=?", (now,))
            row = conn.execute("SELECT * FROM users WHERE id=? AND disabled=0", (user_id,)).fetchone()
            if row is None:
                raise AuthError("auth_required", "请重新登录。", 401)
            conn.execute("INSERT INTO login_sessions VALUES (?,?,?,?)", (_token_hash(token), user_id, now, expires))
            # Bound concurrent sessions without exposing their tokens.
            conn.execute("DELETE FROM login_sessions WHERE user_id=? AND token_hash NOT IN (SELECT token_hash FROM login_sessions WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 10)", (user_id, user_id))
            user = self.public_user(row)
        return token, user, expires

    def resolve_session(self, token):
        if not isinstance(token, str) or not 40 <= len(token) <= 64:
            return None
        with self.connection() as conn:
            row = conn.execute("SELECT u.*,s.expires_at FROM login_sessions s JOIN users u ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0", (_token_hash(token), self.clock())).fetchone()
        return (self.public_user(row), row["expires_at"]) if row else None

    def logout(self, token):
        if isinstance(token, str):
            with self.connection() as conn:
                conn.execute("DELETE FROM login_sessions WHERE token_hash=?", (_token_hash(token),))

    def get_api_key(self, user_id):
        with self.connection() as conn:
            row = conn.execute("SELECT api_key_encrypted FROM users WHERE id=? AND disabled=0", (user_id,)).fetchone()
        if not row or not row[0]:
            return ""
        try:
            return self.cipher.decrypt(row[0]).decode()
        except InvalidToken as exc:
            raise AuthError("credential_unavailable", "账号密钥无法解密，请联系管理员或重新设置 DeepSeek API Key。", 503) from exc

    def set_api_key(self, user_id, key):
        key = validate_api_key(key)
        with self.connection() as conn:
            updated = conn.execute("UPDATE users SET api_key_encrypted=? WHERE id=? AND disabled=0", (self.cipher.encrypt(key.encode()), user_id))
            if updated.rowcount != 1:
                raise AuthError("auth_required", "请重新登录。", 401)

    def workspace_for(self, user):
        if user["id"] == OWNER_USERNAME and user["role"] == "owner":
            return self.owner_directory
        if user["role"] != "user" or not re.fullmatch(r"[a-f0-9]{32}", user["id"]):
            raise AuthError("auth_required", "账号工作目录无效。", 401)
        return self.root / "users" / ("user-" + user["id"])

    def prepare_workspace(self, user):
        directory = self.workspace_for(user)
        with self._prepare_lock:
            lock = self._workspace_locks.setdefault(user["id"], threading.RLock())
        with lock:
            if user["role"] == "user":
                directory.mkdir(exist_ok=True, mode=0o700)
                metadata = directory / "account.json"
                if not metadata.exists():
                    metadata.write_text(json.dumps({"user_id": user["id"]}), encoding="utf-8")
                    os.chmod(metadata, 0o600)
            with account_context(self, user), workspace(directory):
                if user["id"] not in self._workspace_initialized:
                    from backend.database import init_db
                    from backend.patterns import init_mastery_db
                    init_db()
                    init_mastery_db()
                    self._workspace_initialized.add(user["id"])
                # Shared definitions are projected while learning records remain private.
                if user["role"] == "user":
                    from backend.catalog import sync_catalog
                    sync_catalog(self.root / "catalog.db")
        return directory


@contextmanager
def account_context(store, user):
    from backend.identity import identity_context
    token = _STORE.set(store)
    try:
        with identity_context(user):
            yield
    finally:
        _STORE.reset(token)


def current_account_api_key():
    from backend.identity import current_identity
    user, store = current_identity(), _STORE.get()
    if not user or user.get("role") not in ("user", "owner") or store is None:
        return ""
    return store.get_api_key(user["id"])


def set_current_account_api_key(key):
    from backend.identity import current_identity
    user, store = current_identity(), _STORE.get()
    if not user or user.get("role") not in ("user", "owner") or store is None:
        raise AuthError("auth_required", "请先登录账号。", 403)
    store.set_api_key(user["id"], key)


class AccountGateway:
    def __init__(self, application, store, *, guest_application=None, secure_cookie=True, origin=None):
        self.application, self.store, self.guest_application = application, store, guest_application
        self.secure_cookie = secure_cookie
        self.cookie_name = COOKIE if secure_cookie else LOCAL_COOKIE
        self.origin = origin.rstrip("/") if origin else None
        if self.origin:
            parsed = urlsplit(self.origin)
            if parsed.path or parsed.query or parsed.fragment or not parsed.netloc or parsed.scheme not in ("https", "http") or (secure_cookie and parsed.scheme != "https"):
                raise RuntimeError("STUDY_AUTH_ORIGIN 必须为站点根域名，生产环境需使用 https")

    @staticmethod
    def response(content, status=200):
        return JSONResponse(content, status_code=status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    def cookie(self, response, token, expires):
        response.set_cookie(self.cookie_name, token, max_age=max(1, int(expires - self.store.clock())), httponly=True,
                            secure=self.secure_cookie, samesite="strict", path="/")

    def clear_cookie(self, response):
        response.delete_cookie(self.cookie_name, path="/", secure=self.secure_cookie, httponly=True, samesite="strict")

    def require_origin(self, request):
        expected = self.origin or str(request.base_url).rstrip("/")
        if request.headers.get("origin") != expected or request.headers.get("sec-fetch-site") == "cross-site":
            raise AuthError("auth_origin_invalid", "请在本站页面内操作。", 403)

    async def payload(self, request):
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            raise AuthError("invalid_request", "请以 JSON 格式提交。", 415)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 16384:
                raise AuthError("auth_body_too_large", "提交内容过大。", 413)
        try:
            obj = json.loads(data)
        except (ValueError, UnicodeError):
            raise AuthError("invalid_request", "提交内容格式错误。")
        if not isinstance(obj, dict):
            raise AuthError("invalid_request", "提交内容格式错误。")
        return obj

    async def auth_route(self, request, resolved, scope, receive, send):
        path, method = request.url.path, request.method
        if path == "/auth/config" and method == "GET":
            return self.response({"enabled": True, "registration_enabled": self.store.registration_enabled,
                                  "verification_channels": ["email"] if self.store.registration_enabled else [],
                                  "guest_enabled": self.guest_application is not None, "deepseek_guide_url": DEEPSEEK_GUIDE_URL})
        if path == "/auth/me" and method == "GET":
            if resolved:
                user, expires = resolved
                return self.response({"authenticated": True, "user": user, "expires_at": _expiry(expires)})
            if self.guest_application is not None:
                await self.guest_application(scope, receive, send)
                return None
            return self.response({"authenticated": False, "user": None, "expires_at": None})
        self.require_origin(request)
        if path == "/auth/guest" and method == "POST" and self.guest_application is not None:
            # Selecting the guest entrance signs this browser out of its account.
            self.store.logout(request.cookies.get(self.cookie_name))
            async def guest_send(message):
                if message["type"] == "http.response.start":
                    response = self.response({})
                    self.clear_cookie(response)
                    message = dict(message)
                    message["headers"] = list(message.get("headers", [])) + [(k, v) for k, v in response.raw_headers if k == b"set-cookie"]
                await send(message)
            await self.guest_application(scope, receive, guest_send)
            return None
        data = await self.payload(request)
        client = request.client.host if request.client else "unknown"
        if path == "/auth/email-code" and method == "POST":
            if data.get("purpose", "register") != "register":
                raise AuthError("unsupported_verification", "目前仅支持邮箱注册验证码。")
            result = await asyncio.to_thread(self.store.send_email_code, data.get("email"), client)
            return self.response(result, 202)
        if path == "/auth/sms-code":
            raise AuthError("sms_disabled", "短信验证尚未启用，请使用邮箱注册。", 503)
        if path == "/auth/register" and method == "POST":
            token, user, expires = await asyncio.to_thread(self.store.register, data.get("username"), data.get("email"), data.get("code"), data.get("password"), data.get("api_key"), client)
        elif path == "/auth/login" and method == "POST":
            token, user, expires = await asyncio.to_thread(self.store.login, data.get("login"), data.get("password"), client)
        elif path == "/auth/logout" and method == "POST":
            await asyncio.to_thread(self.store.logout, request.cookies.get(self.cookie_name))
            response = self.response({"logged_out": True})
            self.clear_cookie(response)
            return response
        elif path == "/auth/api-key" and method == "PUT":
            if not resolved:
                raise AuthError("auth_required", "请先登录账号。", 401)
            await asyncio.to_thread(self.store.set_api_key, resolved[0]["id"], data.get("api_key"))
            return self.response({"api_key_configured": True})
        else:
            raise AuthError("not_found", "没有此接口。", 404)
        # Session rotation on account switching prevents unused old credentials persisting.
        await asyncio.to_thread(self.store.logout, request.cookies.get(self.cookie_name))
        response = self.response({"authenticated": True, "user": user, "expires_at": _expiry(expires)})
        self.cookie(response, token, expires)
        return response

    def public_static(self, path):
        candidate = (ROOT / "frontend" / path.lstrip("/")).resolve()
        return candidate.is_relative_to((ROOT / "frontend").resolve()) and candidate.is_file() and (not path.endswith(".html") or path in ("/login.html", "/deepseek-guide.html"))

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            self.store.prepare()
            bootstrap = self.store.root / "bootstrap"
            bootstrap.mkdir(exist_ok=True, mode=0o700)
            # Initialize framework startup away from the real owner's private DBs.
            from backend.identity import identity_context
            with identity_context({"id": "bootstrap", "username": "bootstrap", "role": "guest"}), workspace(bootstrap):
                await self.application(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        request = Request(scope, receive)
        try:
            resolved = await asyncio.to_thread(self.store.resolve_session, request.cookies.get(self.cookie_name))
            if request.url.path.startswith("/auth/"):
                response = await self.auth_route(request, resolved, scope, receive, send)
                if response is not None:
                    await response(scope, receive, send)
                return
            path = request.url.path
            if path == "/health" and request.method == "GET":
                await self.response({"ok": True, "mode": "accounts", "auth_enabled": True, "registration_enabled": self.store.registration_enabled})(scope, receive, send)
                return
            if path.startswith("/_internal/"):
                # main's deployment guard still checks loopback and forwarded headers.
                bootstrap = self.store.root / "bootstrap"
                bootstrap.mkdir(exist_ok=True, mode=0o700)
                from backend.identity import identity_context
                with identity_context({"id": "bootstrap", "username": "bootstrap", "role": "guest"}), workspace(bootstrap):
                    await self.application(scope, receive, send)
                return
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                self.require_origin(request)
            if resolved:
                user, _ = resolved
                directory = await asyncio.to_thread(self.store.prepare_workspace, user)
                async def account_send(message):
                    if message["type"] == "http.response.start":
                        message = dict(message)
                        message["headers"] = [(k, v) for k, v in message.get("headers", [])
                                              if k.lower() not in (b"cache-control", b"etag", b"last-modified")]
                        message["headers"].append((b"cache-control", b"private, no-store"))
                    await send(message)
                with account_context(self.store, user), workspace(directory):
                    await self.application(scope, receive, account_send)
                return
            if request.method in ("GET", "HEAD") and path == "/":
                page = ROOT / "frontend" / "login.html"
                if not page.exists():
                    raise AuthError("auth_page_unavailable", "登录页面正在准备，请稍后重试。", 503)
                await HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})(scope, receive, send)
                return
            if request.method in ("GET", "HEAD") and self.public_static(path):
                # Static reads cannot see any account workspace.
                await self.application(scope, receive, send)
                return
            if request.method in ("GET", "HEAD") and path.endswith(".html") and not any(
                request.cookies.get(name) for name in ("__Host-study_demo", "study_demo_local")
            ):
                await RedirectResponse("/login.html", status_code=303)(scope, receive, send)
                return
            if self.guest_application is not None:
                await self.guest_application(scope, receive, send)
                return
            raise AuthError("auth_required", "请登录账号或选择游客体验。", 401)
        except AuthError as exc:
            await self.response({"error": exc.code, "detail": exc.detail}, exc.status)(scope, receive, send)


def install_account_gateway(app, owner_directory, *, store=None, guest_application=None):
    """Return an ASGI wrapper; never enables accounts or mutates DBs on import."""
    store = store or AccountStore(os.environ.get("STUDY_AUTH_ROOT", str(ROOT / ".accounts")), owner_directory)
    secure = os.environ.get("STUDY_AUTH_COOKIE_SECURE", "1") != "0"
    return AccountGateway(app, store, guest_application=guest_application, secure_cookie=secure,
                          origin=os.environ.get("STUDY_AUTH_ORIGIN") or None)
