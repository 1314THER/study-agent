"""Request identity, propagated to the existing background job context."""

from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException

_IDENTITY = ContextVar("study_identity", default=None)


def current_identity():
    return _IDENTITY.get()


@contextmanager
def identity_context(user):
    token = _IDENTITY.set(user)
    try:
        yield
    finally:
        _IDENTITY.reset(token)


def current_user_id():
    user = current_identity()
    return str(user["id"]) if user is not None else "studyadmin"


def can_edit_catalog():
    user = current_identity()
    # The private legacy process is still protected by its existing gateway.
    return user is None or (user.get("role") == "owner" and user.get("username") == "studyadmin")


def require_catalog_editor():
    if not can_edit_catalog():
        raise HTTPException(status_code=403, detail="公共母题仅允许主人 studyadmin 编辑。")
