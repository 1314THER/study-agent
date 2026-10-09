"""Select mutable data files for the current request or application process.

The regular application keeps its original paths. Demo requests enter
``workspace(directory)`` so database and configuration writes stay in that
visitor's directory, including work run through AnyIO's thread pool.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import os
from typing import Iterator, Optional, Union


_WORKSPACE: ContextVar[Optional[str]] = ContextVar("study_agent_workspace", default=None)
_BACKGROUND_LEASE = ContextVar("study_agent_background_lease", default=None)


@contextmanager
def background_lease(factory):
    """Propagate a demo lifetime lease factory to background AI workers."""
    token = _BACKGROUND_LEASE.set(factory)
    try:
        yield
    finally:
        _BACKGROUND_LEASE.reset(token)


def acquire_background_lease():
    """Keep a demo workspace alive until an async job calls the returned release."""
    factory = _BACKGROUND_LEASE.get()
    return factory() if factory is not None else (lambda: None)


def workspace_directory() -> Optional[str]:
    """Return the request directory, then the process override, if configured."""
    directory = _WORKSPACE.get()
    if directory is not None:
        return directory
    configured = os.environ.get("STUDY_AGENT_DATA_DIR", "").strip()
    return os.path.abspath(os.path.expanduser(configured)) if configured else None


def shared_ai_config_path() -> Optional[str]:
    """Return the administrator's read-only demo AI snapshot in a workspace.

    This path is deliberately independent of ``data_path``: shared credentials
    stay outside visitor directories. The regular owner app never reads it.
    """
    if workspace_directory() is None:
        return None
    configured = os.environ.get("STUDY_DEMO_AI_CONFIG", "").strip()
    return os.path.abspath(os.path.expanduser(configured)) if configured else None


@contextmanager
def workspace(directory: Union[str, os.PathLike]) -> Iterator[None]:
    """Use an existing directory for data and restore the previous context."""
    directory = os.path.abspath(os.path.expanduser(os.fspath(directory)))
    token = _WORKSPACE.set(directory)
    try:
        yield
    finally:
        _WORKSPACE.reset(token)


def data_path(filename: str, legacy_default: Union[str, os.PathLike]) -> str:
    """Resolve a known data filename without changing the normal app defaults."""
    directory = workspace_directory()
    return os.path.join(directory, filename) if directory is not None else os.fspath(legacy_default)
