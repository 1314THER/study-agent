"""Bound form parsing and JSON before either can allocate unbounded storage."""
from starlette.responses import JSONResponse


class BodyLimit:
    def __init__(self, app):
        self.app = app
        self.state = app.state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = 33 * 1024 * 1024 if scope["path"] == "/api/v1/assets" else 2 * 1024 * 1024
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                await JSONResponse({"error": "body_too_large", "detail": "提交内容过大"}, status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)
