"""Reusable question-to-routine matching and human review, independent of banks.

The engine takes a catalogue and an injected AI caller. HTTP, CLI, question
importers and learning features can all call it without loading the application
or establishing formal question/pattern links. Catalogue IDs have their own
namespace and must never be treated as integer mastery.db pattern IDs.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import re
import threading
import unicodedata

from backend import routine_classification as rc


CATEGORY_PREFIXES = dict(zip(rc.CATEGORY_COUNTS,
                            ("SET", "INEQ", "QUAD", "FUNC", "EXP", "TRIG", "VEC", "CPLX", "SOLID", "SEQ", "GEO", "PROB")))
DRAFT_FIELDS = ("name", "category", "signals", "retrieval_terms", "key_steps", "exclusions", "confusable_ids", "aliases")
_LOCK = threading.RLock()


class MatchFailure(Exception):
    def __init__(self, cause, partial):
        super().__init__(rc._safe_failure(cause))
        self.cause, self.partial = cause, partial


def question_record(question, *, solution="", answer="", categories=None,
                    completeness="unknown", id=1, version=1):
    """Validate one in-memory question using the same contract as JSONL inputs."""
    if type(id) is not int or id < 1 or type(version) is not int or version < 1:
        raise ValueError("题目编号和版本须为正整数")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("题干不能为空")
    if any(not isinstance(v, str) for v in (solution, answer, completeness)):
        raise ValueError("答案、原解析与完整性须为文字")
    categories = [] if categories is None else categories
    rc._strings(categories, "板块", minimum=0)
    if not set(categories) <= set(rc.CATEGORY_COUNTS):
        raise ValueError("含未知板块")
    return dict(id=id, version=version, question=question, solution=solution, answer=answer,
                categories=categories[:], completeness=completeness)


def match_question(item, catalog, caller, *, attempts=2, initial=None, checkpoint=None, retriever=None):
    """Return an advisory match. Uncertain complete items get a full audit.

    A checkpoint contains the successful retrieval pass, so an interrupted or
    failed full audit can resume without paying for that first pass again.
    Each stage retries independently. This function never writes files itself.
    """
    item = question_record(**item)
    if attempts not in (1, 2, 3):
        raise ValueError("attempts 须为 1–3")
    partial = {k: deepcopy(v) for k, v in (initial or {}).items()
               if k in ("classification", "catalog_audited", "audit_pending", "retrieved_ids")}
    calls = 0
    choices = None if partial.get("audit_pending") else (retriever or rc.shortlist)(item, catalog)

    def invoke(full, previous=None):
        nonlocal calls
        system, user, allowed = rc.make_prompt(item, catalog, full_catalog=full, previous=previous, choices=choices)
        for attempt in range(attempts):
            try:
                calls += 1
                return rc.normalize_result(caller(system, user, item), item, catalog, allowed)
            except Exception as exc:
                if attempt + 1 == attempts:
                    raise MatchFailure(exc, {**partial, "api_attempts": calls}) from None

    if partial.get("audit_pending"):
        first = rc.normalize_result(partial["classification"], item, catalog)
    else:
        first = invoke(False)
        partial = {"classification": first, "catalog_audited": False, "audit_pending": False,
                   "retrieved_ids": list(dict.fromkeys(r["id"] for r in (choices or catalog["routines"])))}
    uncertain = first["primary_routine_id"] is None or first["confidence"] != "high" or first["suggested_routine"] is not None
    complete = bool(item["solution"].strip()) and item["completeness"] == "complete"
    if complete and uncertain:
        partial["audit_pending"] = True
        if checkpoint:
            checkpoint(partial)
        final = invoke(True, first)
        partial.update(classification=final, catalog_audited=True, audit_pending=False)
    return {k: v for k, v in {**partial, "api_attempts": calls}.items()
            if k in ("classification", "catalog_audited", "audit_pending", "retrieved_ids", "api_attempts")}


def _name_key(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).casefold()


def validate_draft(draft, catalog):
    if not isinstance(draft, dict) or any(field not in draft for field in DRAFT_FIELDS):
        raise ValueError("新套路须补齐名称、板块、识别特征、检索词、步骤、排除条件、易混淆编号和别名")
    if not isinstance(draft["name"], str) or not draft["name"].strip() or not isinstance(draft["category"], str) or draft["category"] not in CATEGORY_PREFIXES:
        raise ValueError("新套路名称或板块无效")
    if _name_key(draft["name"]) in {_name_key(r["name"]) for r in catalog["routines"]}:
        raise ValueError("目录已有同名套路，请归入已有项或重新核对方法差异")
    for field in DRAFT_FIELDS[2:]:
        rc._strings(draft[field], "新套路." + field, minimum=0 if field == "aliases" else 1)
    others = draft["confusable_ids"]
    if len(others) > 3 or len(others) != len(set(others)) or not set(others) <= {r["id"] for r in catalog["routines"]}:
        raise ValueError("易混淆套路必须是已有目录编号，最多 3 个")
    return {k: deepcopy(draft[k]) for k in DRAFT_FIELDS}


def build_review_entry(row, catalog):
    """Separate missing information, ambiguous matches and plausible novelty."""
    result = row.get("classification") or {}
    if row["status"] == "pending":
        return None
    if row.get("override_status") == "applied" and not result.get("needs_review"):
        return None
    if row["status"] == "classified" and not result.get("needs_review") and row.get("override_status") != "stale":
        return None
    item = row.get("item") or {k: row[k] for k in ("id", "version", "question", "completeness")}
    item = question_record(**item)
    kind = "ambiguous_match"
    reasons = result.get("review_reasons", [])[:]
    draft = result.get("suggested_routine")
    if row.get("override_status") == "stale":
        reasons.append("人工修正已经过期，请按新版本重新核对")
    if row["status"] in ("error", "matching"):
        kind = "matching_incomplete"
        reasons.append(row.get("error") or "全目录复查尚未完成，可续跑")
    elif not item["solution"].strip() or item["completeness"] != "complete":
        kind = "insufficient_content"
        reasons.append("先补齐原解析或题目条件，不能据此确认新套路")
    elif result.get("primary_routine_id") is None and not result.get("composite"):
        try:
            validate_draft(draft, catalog)
            if not row.get("catalog_audited") or not result.get("evidence") or not result.get("novelty_checks"):
                raise ValueError("全目录复查、原文证据或已有套路排除理由不足")
            kind = "new_routine_candidate"
            reasons.append("全目录复查仍无合适项；草案等待人工确认，不自动新建")
        except ValueError as exc:
            reasons.append(str(exc))
    entry = {"item": item, "content_hash": rc.digest(item), "kind": kind, "status": "pending",
             "catalog_hash": rc.digest(catalog), "catalog_version": catalog["version"],
             "classification": result, "catalog_audited": bool(row.get("catalog_audited")),
             "draft": draft, "novelty_checks": result.get("novelty_checks", []),
             "reasons": list(dict.fromkeys(reasons))}
    # One review per exact question/version and catalogue/prompt snapshot.
    # Model wording or cache normalization must not create duplicate queue rows.
    entry["review_id"] = "review-" + rc.digest({"content_hash": entry["content_hash"],
                                               "catalog_hash": entry["catalog_hash"],
                                               "prompt_version": rc.PROMPT_VERSION})[:24]
    return entry


def apply_review_decision(catalog, entry, decision):
    """Pure human decision -> proposed catalogue + version-bound correction."""
    if not isinstance(decision, dict) or decision.get("confirmed") is not True:
        raise ValueError("需人工确认 confirmed=true；AI 草案不能自行批准")
    if decision.get("action") not in ("create", "use_existing", "defer", "reject"):
        raise ValueError("审核动作须为 create/use_existing/defer/reject")
    if decision.get("expected_catalog_hash") != rc.digest(catalog):
        raise ValueError("目录已经变更，请获取当前目录并重新审核")
    note = decision.get("note")
    if not isinstance(note, str) or not note.strip():
        raise ValueError("请填写人工审核说明")
    item = question_record(**entry["item"])
    if entry.get("content_hash") != rc.digest(item):
        raise ValueError("审核题目内容已变更")
    updated = deepcopy(catalog)
    rid = None
    action = decision["action"]
    if action == "create":
        if entry.get("kind") != "new_routine_candidate" or entry.get("catalog_hash") != rc.digest(catalog):
            raise ValueError("只能确认当前目录下完成复查的新套路候选；资料不足或旧目录建议须重新匹配")
        # Re-evaluate the entry rather than trusting an editable queue's kind.
        checked = build_review_entry({"status": "classified", "item": item,
                                      "classification": rc.normalize_result(entry["classification"], item, catalog),
                                      "catalog_audited": entry.get("catalog_audited")}, catalog)
        if not checked or checked["kind"] != "new_routine_candidate":
            raise ValueError("该候选缺少新建所需的全目录复查或证据")
        draft = validate_draft(entry["draft"] if decision.get("draft") is None else decision["draft"], catalog)
        prefix = CATEGORY_PREFIXES[draft["category"]]
        number = 1 + max((int(r["id"].split("-")[1]) for r in catalog["routines"]
                          if r["id"].startswith(prefix + "-")), default=0)
        rid = f"{prefix}-{number:03d}"
        updated["routines"].append({"id": rid, **draft})
        revision = re.fullmatch(r"(.*)\.r(\d+)", catalog["version"])
        updated["version"] = (revision[1] + f".r{int(revision[2]) + 1}") if revision else catalog["version"] + ".r1"
        rc.validate_catalog(updated)
    elif action == "use_existing":
        rid = decision.get("routine_id")
        if not isinstance(rid, str) or rid not in {r["id"] for r in catalog["routines"]}:
            raise ValueError("请指定有效的已有套路编号")
    record = {"review_id": entry["review_id"], "action": action, "routine_id": rid, "note": note,
              "catalog_before": rc.digest(catalog), "catalog_after": rc.digest(updated),
              "item_id": item["id"], "item_version": item["version"], "content_hash": rc.digest(item)}
    override = {"id": item["id"], "version": item["version"], "content_hash": rc.digest(item),
                "primary_routine_id": rid, "secondary_routine_ids": [], "note": note}
    return updated, record, override


class RoutineMatchingStore:
    """Workspace-local JSON review store; atomic catalogue + decision updates.

    No filesystem path is supplied by API clients. Imports and read-only
    requests do not create files. The checked-in baseline is never overwritten.
    """
    def __init__(self, directory, baseline=rc.DEFAULT_CATALOG):
        self.directory, self.baseline = Path(directory), Path(baseline)

    @property
    def path(self):
        return self.directory / "state.json"

    def read(self):
        if not self.path.exists():
            return {"schema_version": 1, "catalog": rc.load_catalog(self.baseline), "reviews": {}, "decisions": {}, "history": []}
        state = rc.read_json(self.path)
        if not isinstance(state, dict) or state.get("schema_version") != 1 or not isinstance(state.get("reviews"), dict) or not isinstance(state.get("decisions"), dict):
            raise ValueError("匹配审核存储格式无效")
        rc.validate_catalog(state.get("catalog"))
        return state

    @contextmanager
    def locked(self):
        # File locks also cover multiple workers on supported deployment hosts.
        import fcntl
        with _LOCK:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / ".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def enqueue(self, entry):
        with self.locked():
            state = self.read()
            if entry["catalog_hash"] != rc.digest(state["catalog"]):
                raise ValueError("匹配期间目录已变更，请使用当前目录重新匹配")
            existing = state["reviews"].get(entry["review_id"])
            if existing:
                return existing
            state["reviews"][entry["review_id"]] = entry
            rc.write_json(self.path, state)
        return entry

    def decide(self, review_id, decision):
        with self.locked():
            state = self.read()
            if review_id not in state["reviews"]:
                raise KeyError("审核项不存在")
            if review_id in state["decisions"]:
                saved = state["decisions"][review_id]
                if saved["request_hash"] == rc.digest(decision):
                    return saved
                if saved["action"] != "defer":
                    raise ValueError("审核项已有不同决定，请重新匹配后再审核")
            catalog, record, override = apply_review_decision(state["catalog"], state["reviews"][review_id], decision)
            record.update(request_hash=rc.digest(decision), override=override)
            state["catalog"] = catalog
            state["decisions"].pop(review_id, None)
            state["decisions"][review_id] = record
            state.setdefault("history", []).append(record)
            state["reviews"][review_id].update(status=decision["action"], decision=record)
            rc.write_json(self.path, state)
        return record
