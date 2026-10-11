"""Conservative exam-year evidence shared by every question-pool entry point.

Never search a question, answer, solution, update date or repository revision.
Conflicting years and academic-year ranges are unknown, not grounds for deletion.
"""
import re
from copy import deepcopy

MIN_YEAR = 2016
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_RANGE = re.compile(r"(?:19|20)\d{2}\s*[-—–/至]\s*(?:19|20)\d{2}")


def default_mock_years():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    year = datetime.now(ZoneInfo("Asia/Shanghai")).year
    return [year - 1, year]


def normalize_year(value):
    if isinstance(value, bool):
        return None
    text = str(value or "").strip()
    if re.fullmatch(r"(?:19|20)\d{2}年?", text):
        return int(text.rstrip("年"))
    return None


def _title_year(value):
    text = str(value or "")
    # A school year alone does not tell us when this particular exam was held.
    text = _RANGE.sub("", text)
    years = set(int(m[0]) for m in _YEAR.finditer(text))
    return next(iter(years)) if len(years) == 1 else None


def year_evidence(record, source=None):
    """Return JSON-safe evidence from structured metadata and source locators."""
    record = record or {}
    raw = record.get("raw") if isinstance(record.get("raw"), dict) else {}
    original = raw.get("original") if isinstance(raw.get("original"), dict) else {}
    meta = record.get("source_meta") if isinstance(record.get("source_meta"), dict) else {}
    evidence = []
    for obj, prefix in ((record, "metadata"), (original, "original"), (meta, "source_meta")):
        for field in ("year", "exam_year", "examYear"):
            year = normalize_year(obj.get(field))
            if year is not None:
                evidence.append({"field": prefix + "." + field, "value": obj[field], "year": year})
    for obj, prefix in ((record, "metadata"), (raw, "raw"), (original, "original"), (meta, "source_meta")):
        for field in ("paper", "paperTitle", "paper_title", "exam_title", "file", "filename"):
            year = _title_year(obj.get(field))
            if year is not None:
                evidence.append({"field": prefix + "." + field, "value": obj[field], "year": year})
    # An original paper locator takes precedence over a dated collection's name.
    if source and not evidence:
        year = _title_year(source.get("filename"))
        if year is not None:
            evidence.append({"field": "source.filename", "value": source["filename"], "year": year})
    years = {e["year"] for e in evidence}
    return {"year": next(iter(years)) if len(years) == 1 else None,
            "status": "known" if len(years) == 1 else "conflict" if years else "unknown",
            "evidence": evidence}


def is_old(record, source=None):
    year = year_evidence(record, source)["year"]
    return year is not None and year < MIN_YEAR


def apply_year_policy(record, source=None):
    """Normalize an accepted record, preserving all original evidence."""
    item = deepcopy(record)
    evidence = year_evidence(item, source)
    item["year"] = evidence["year"]
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    item["raw"] = {**raw, "year_status": evidence["status"], "year_evidence": evidence}
    return item
