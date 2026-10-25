"""Shared system API for advisory matches; does not read or write question banks."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictBool, StrictStr, conint

from backend import routine_classification as rc
from backend.routine_matching import (MatchFailure, RoutineMatchingStore,
                                      build_review_entry, match_question, question_record)


router = APIRouter(prefix="/routine-matching", tags=["套路匹配"])
PositiveStrictInt = conint(strict=True, ge=1)


class QuestionInput(BaseModel):
    question: StrictStr = Field(..., min_length=1, max_length=50000)
    solution: StrictStr = Field("", max_length=100000)
    answer: StrictStr = Field("", max_length=20000)
    categories: List[StrictStr] = Field(default_factory=list, max_items=12)
    completeness: Literal["complete", "unknown", "needs_review", "deferred_graphic", "failed"] = "unknown"
    id: PositiveStrictInt = 1
    version: PositiveStrictInt = 1

    class Config:
        extra = "forbid"


class MatchInput(QuestionInput):
    save_review: StrictBool = True


class RoutineDraft(BaseModel):
    name: StrictStr = Field(..., min_length=1, max_length=200)
    category: StrictStr
    signals: List[StrictStr] = Field(..., min_items=1, max_items=10)
    retrieval_terms: List[StrictStr] = Field(..., min_items=1, max_items=30)
    key_steps: List[StrictStr] = Field(..., min_items=1, max_items=20)
    exclusions: List[StrictStr] = Field(..., min_items=1, max_items=10)
    confusable_ids: List[StrictStr] = Field(..., min_items=1, max_items=3)
    aliases: List[StrictStr] = Field(default_factory=list, max_items=10)

    class Config:
        extra = "forbid"


class ReviewDecision(BaseModel):
    action: Literal["create", "use_existing", "defer", "reject"]
    confirmed: StrictBool = False
    expected_catalog_hash: StrictStr = Field(..., min_length=64, max_length=64)
    note: StrictStr = Field(..., min_length=1, max_length=5000)
    routine_id: Optional[StrictStr] = None
    draft: Optional[RoutineDraft] = None

    class Config:
        extra = "forbid"


def get_store():
    from backend.data_paths import data_path
    return RoutineMatchingStore(data_path("routine-matching", rc.ROOT / ".runtime" / "routine-matching"))


def get_ai_caller():
    """Reuse account/provider configuration and the system's AI concurrency limit."""
    from backend import settings
    from backend.jobs import request_timeout
    limits = settings.get_limits()
    teacher_cfg = settings.get_teacher_config("liangliang")["solver"]
    model = teacher_cfg.get("model") or "glm-4.7-flash"
    provider = "zhipu" if model.startswith("glm-") else "deepseek"
    api = settings.get_api().get(provider) or {}
    config = {"model": model, "provider": provider,
              "base_url": api.get("base_url") or settings.DEFAULTS["api"][provider]["base_url"],
              "temperature": 0.1, "reasoning_effort": teacher_cfg.get("reasoning_effort") or "medium",
              "max_tokens": min(8192, int(limits.get("api_max_tokens", 8192))), "json_output": True}
    if not model.startswith("gpt-") and not settings.get_api_key(provider):
        raise HTTPException(503, "请先在系统设置中配置所选模型服务的 API Key。")
    timeout = min(120, int(limits.get("api_timeout_seconds", 120)))

    return rc.make_teacher_caller(config, timeout_seconds=request_timeout(timeout))


def _dump(model, **kwargs):
    return model.model_dump(**kwargs) if hasattr(model, "model_dump") else model.dict(**kwargs)


def _item(request):
    values = _dump(request)
    values.pop("save_review", None)
    try:
        return question_record(**values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/catalog")
def api_catalog(store=Depends(get_store)):
    catalog = store.read()["catalog"]
    return {"catalog": catalog, "catalog_hash": rc.digest(catalog), "advisory_only": True,
            "id_namespace": "routine_catalog (independent of mastery.db pattern_id)"}


@router.post("/retrieve")
def api_retrieve(request: QuestionInput, store=Depends(get_store)):
    item, catalog = _item(request), store.read()["catalog"]
    return {"candidates": rc.shortlist(item, catalog), "catalog_hash": rc.digest(catalog),
            "catalog_version": catalog["version"], "ai_called": False, "advisory_only": True}


@router.post("/match")
def api_match(request: MatchInput, store=Depends(get_store)):
    item, state = _item(request), store.read()
    catalog = state["catalog"]
    # Exact, version-bound manual decisions take priority across calling features.
    human = next((d for d in reversed(list(state["decisions"].values()))
                       if d["content_hash"] == rc.digest(item) and d["item_version"] == item["version"]), None)
    if human:
        row = rc.apply_override({"status": "pending", "item": item}, item, human["override"])
        matched = {"classification": row["classification"], "catalog_audited": False,
                   "audit_pending": False, "api_attempts": 0, "human_decision_applied": True}
    else:
        # Resolve credentials only when AI is actually needed.
        caller = get_ai_caller()
        try:
            matched = match_question(item, catalog, caller)
        except MatchFailure as exc:
            raise HTTPException(502, rc._safe_failure(exc.cause)) from None
    entry = build_review_entry({"status": "classified", "item": item, **matched}, catalog)
    if human and human["action"] in ("defer", "reject"):
        entry = state["reviews"][human["review_id"]]
    elif entry and request.save_review:
        try:
            entry = store.enqueue(entry)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    primary = matched["classification"]["primary_routine_id"]
    return {**matched, "primary_routine": next((r for r in catalog["routines"] if r["id"] == primary), None),
            "catalog_hash": rc.digest(catalog), "catalog_version": catalog["version"],
            "review": entry, "review_saved": bool(entry and request.save_review), "advisory_only": True}


@router.get("/reviews")
def api_reviews(status: Literal["pending", "all"] = "pending", offset: int = Query(0, ge=0),
                limit: int = Query(50, ge=1, le=200), store=Depends(get_store)):
    state = store.read()
    catalog_hash = rc.digest(state["catalog"])
    entries = [{**entry, "catalog_stale": entry["catalog_hash"] != catalog_hash}
               for entry in state["reviews"].values()
               if status == "all" or entry["status"] in ("pending", "defer")]
    return {"entries": entries[offset:offset + limit], "total": len(entries),
            "catalog_hash": catalog_hash, "catalog_version": state["catalog"]["version"], "advisory_only": True}


@router.post("/reviews/{review_id}/decision")
def api_decision(review_id: str, request: ReviewDecision, store=Depends(get_store)):
    if request.action == "create":
        from backend.identity import require_catalog_editor
        require_catalog_editor()
        from backend.data_paths import _BACKGROUND_LEASE
        from backend.identity import current_identity
        if current_identity() is None and _BACKGROUND_LEASE.get() is not None:
            raise HTTPException(403, "新套路参考目录仅供主人维护。")
    try:
        decision = store.decide(review_id, _dump(request, exclude_none=True))
    except KeyError:
        raise HTTPException(404, "审核项不存在。") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"decision": decision, "advisory_only": True, "formal_pattern_created": False}
