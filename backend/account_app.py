"""Public account application: three entrances and one owner-published catalog."""

import asyncio
import json
import logging
import os
from pathlib import Path
import re

from backend.auth import AccountStore, AccountGateway
from backend.catalog import publish_catalog
from backend.data_paths import workspace
from backend.identity import current_identity, identity_context

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


class CatalogApplication:
    def __init__(self, application, store):
        self.application, self.store = application, store

    def initialize_owner(self):
        from backend.database import init_db
        from backend.patterns import init_mastery_db, sync_mother_questions
        self.store.owner_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with identity_context({"id": "studyadmin", "username": "studyadmin", "role": "owner"}), workspace(self.store.owner_directory):
            init_db()
            init_mastery_db()
            sync_mother_questions()
            publish_catalog(self.store.owner_directory, self.store.root / "catalog.db")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            async def initialized_send(message):
                if message["type"] == "lifespan.startup.complete":
                    await asyncio.to_thread(self.initialize_owner)
                await send(message)
            await self.application(scope, receive, initialized_send)
            return
        user = current_identity()
        owner = user and user.get("role") == "owner"
        if owner:
            await asyncio.to_thread(publish_catalog, self.store.owner_directory, self.store.root / "catalog.db")
        start, chunks, html, status = None, [], False, None

        async def personal_send(message):
            nonlocal start, html, status
            if message["type"] == "http.response.start":
                status = message["status"]
                start = dict(message)
                start["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"cache-control", b"etag", b"last-modified")]
                start["headers"].append((b"cache-control", b"no-store"))
                html = bool(user and scope["method"] == "GET" and any(k == b"content-type" and b"text/html" in v for k, v in start["headers"]))
                if not html:
                    await send(start)
            elif message["type"] == "http.response.body" and html:
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    public_user = {k: user[k] for k in ("id", "username", "role", "api_key_configured") if k in user}
                    boot = ("<script>window.STUDY_USER=" + json.dumps(public_user, ensure_ascii=True) + ";</script>").encode()
                    data = re.sub(br"(<head\b[^>]*>)", lambda m: m.group(1) + boot, b"".join(chunks), count=1, flags=re.I)
                    start["headers"] = [(k, v) for k, v in start["headers"] if k != b"content-length"]
                    start["headers"].append((b"content-length", str(len(data)).encode()))
                    await send(start)
                    await send({"type": "http.response.body", "body": data})
            else:
                await send(message)
        await self.application(scope, receive, personal_send)
        if owner and scope["method"] not in ("GET", "HEAD", "OPTIONS") and status is not None and status < 400:
            await asyncio.to_thread(publish_catalog, self.store.owner_directory, self.store.root / "catalog.db")


def build_account_app(application, *, store=None, guest_store=None, local_preview=None):
    owner_directory = os.environ.get("STUDY_OWNER_DATA_DIR") or os.environ.get("STUDY_AGENT_DATA_DIR") or str(ROOT)
    store = store or AccountStore(os.environ.get("STUDY_AUTH_ROOT", str(ROOT / ".accounts")), owner_directory)
    from backend.demo import DemoGateway, SessionStore
    if local_preview is None:
        local_preview = os.environ.get("STUDY_AUTH_COOKIE_SECURE", "1") == "0"
    guest_store = guest_store or SessionStore(Path(os.environ.get("STUDY_DEMO_ROOT", str(store.root / "guests"))), account_mode=True)
    guest_store.account_mode = True
    core = CatalogApplication(application, store)
    guest = DemoGateway(core, guest_store, ai_enabled=os.environ.get("STUDY_DEMO_AI_ENABLED", "1") == "1", local_preview=local_preview, account_mode=True, catalog_path=store.root / "catalog.db")
    return AccountGateway(core, store, guest_application=guest, secure_cookie=not local_preview, origin=os.environ.get("STUDY_AUTH_ORIGIN") or None)
