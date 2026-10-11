"""Adapter and whole-paper checks for cheese233/gaokao-related-math JSONL.

Answers are source material only. Nothing here calls a solver or invents answers.
"""
from collections import Counter, defaultdict
from pathlib import Path
import re

DATASET_URL = "https://huggingface.co/datasets/cheese233/gaokao-related-math"
DATASET_REVISION = "202c7cfc5b32264cecccf629c31b592cc702afed"
TYPES = {"single": "选择题", "multiple": "多选题", "fill": "填空题", "solve": "大题"}
EXPECTED = {n: "single" if n <= 8 else "multiple" if n <= 11 else "fill" if n <= 14 else "solve" for n in range(1, 20)}


def _number(value):
    try:
        return int(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _paper_id(item):
    return str(item.get("paperId") or item.get("paper_id") or item.get("paperUrl") or item.get("paperTitle") or "")


def validate_paper(items):
    counts = Counter(_number(i.get("qNo")) for i in items)
    errors = []
    if set(counts) != set(EXPECTED) or any(n != 1 for n in counts.values()):
        errors.append("实际题号必须为 1 至 19，各出现一次")
    if any(i.get("qType") != EXPECTED.get(_number(i.get("qNo"))) for i in items):
        errors.append("实际题型不符合 8 单选＋3 多选＋3 填空＋5 解答")
    if len({str(i.get("year")) for i in items}) != 1 or len({str(i.get("province")) for i in items}) != 1:
        errors.append("同一卷的年份或省份元数据冲突")
    return {"valid": not errors, "errors": errors, "actual_count": len(items),
            "types": dict(Counter(i.get("qType") for i in items)), "question_numbers": sorted(n for n in counts if n is not None)}


def iter_gaokao_related(root, options=None):
    from backend.pool_sources import _files, _json_items, _record, _error, _string, _relative, classify_categories
    from backend.source_policy import normalize_year
    options = options or {}
    revision = options.get("dataset_revision") or DATASET_REVISION
    report = options.get("source_report")
    if report is None:
        report = {}
    report.update(total_rows=0, selected_papers=0, selected_rows=0, matched_answers=0, missing_answers=0,
                  skipped_year=0, skipped_region=0, skipped_not_mock=0, invalid_papers=[], papers=[])
    groups = defaultdict(list)
    for file in _files(root, {".jsonl", ".json"}):
        if file.name.endswith("manifest.json"):
            continue
        for index, item, error in _json_items(file):
            report["total_rows"] += 1
            if error or not isinstance(item, dict) or not _paper_id(item):
                yield _error(f"{_relative(file, root)}#{index}", error or "缺少试卷标识", {"file": str(file), "index": index, "original": item})
                continue
            groups[_paper_id(item)].append((file, index, item))
    answers = defaultdict(list)
    if options.get("answers_path"):
        for _, item, error in _json_items(Path(options["answers_path"])):
            if not error and isinstance(item, dict) and _paper_id(item):
                answers[(_paper_id(item), str(item.get("qNo", item.get("question_no", ""))))].append(item)
    years = set(options.get("mock_years", [2025, 2026]))
    for pid, entries in groups.items():
        items = [i for _, _, i in entries]
        if options.get("mock_profile", True):
            if any(normalize_year(i.get("year")) not in years for i in items):
                report["skipped_year"] += len(items)
                continue
            if any(re.match(r"^(?:北京|天津|上海)", str(i.get("province", ""))) or
                   re.search(r"北京|天津|上海", str(i.get("paperTitle", ""))) for i in items):
                report["skipped_region"] += len(items)
                continue
            if any("模拟" not in str(i.get("paperType", "")) for i in items):
                report["skipped_not_mock"] += len(items)
                continue
        validation = validate_paper(items)
        paper_info = {"paper_id": pid, "paper": items[0].get("paperTitle"), "year": items[0].get("year"),
                      "province": items[0].get("province"), "url": items[0].get("paperUrl"), **validation}
        if options.get("require_19", True) and not validation["valid"]:
            report["invalid_papers"].append(paper_info)
            continue
        report["papers"].append(paper_info)
        report["selected_papers"] += 1
        for file, index, item in sorted(entries, key=lambda e: (_number(e[2].get("qNo")) or 0, e[1])):
            qno = str(item.get("qNo", ""))
            stem = re.sub(r"\{#blank#\}.*?\{#/blank#\}", "____", _string(item.get("stem")), flags=re.S)
            choices = item.get("options") if isinstance(item.get("options"), list) else []
            lines = [stem] + [f"{_string(o.get('label'))}. {_string(o.get('content'))}" for o in choices if isinstance(o, dict)]
            answer = _string(item.get("answer"))
            solution = _string(item.get("solution", item.get("analysis")))
            matches = answers.get((pid, qno), [])
            if len(matches) == 1:
                answer = answer or _string(matches[0].get("answer"))
                solution = solution or _string(matches[0].get("solution", matches[0].get("analysis")))
                report["matched_answers"] += int(bool(answer))
            images = item.get("images") if isinstance(item.get("images"), list) else []
            image_refs = [{"path": p, "repo_path": "data/" + str(p).lstrip("/"),
                           "url": DATASET_URL + "/resolve/" + revision + "/data/" + str(p).lstrip("/")} for p in images]
            reason = "结构化题干候选，题干、选项、公式及图形完整性待核对"
            if len(matches) > 1:
                reason += "；同一试卷题号存在多个答案，未自动关联"
            if not validation["valid"]:
                reason += "；19 题结构核验未通过"
            tags = []
            if re.search(r"导数|导函数|极值|[fgh]['′]|\\prime", stem):
                tags.append("导数")
            if re.search(r"概率|随机|分布列|数学期望", stem):
                tags.append("概率统计")
                if re.search(r"递推|转移|重复|第.*次|直到|停止|博弈|策略|取决|n次|n 次", stem):
                    tags.append("综合概率候选")
            report["selected_rows"] += 1
            report["missing_answers"] += int(not answer)
            region = _string(item.get("province"))
            if region.lower() in ("null", "none", "unknown"):
                region = ""
                reason += "；省份未知"
            yield _record(f"paper-{pid}#q{qno}", "\n".join(lines), answer, solution,
                          year=item.get("year"), region=region, question_no=qno,
                          question_type=TYPES.get(item.get("qType"), ""), categories=classify_categories(stem),
                          completeness="deferred_graphic" if images else "needs_review", reason=reason,
                          raw={"file": _relative(file, root), "index": index, "original": item,
                               "paper": item.get("paperTitle"), "paper_id": pid, "paper_url": item.get("paperUrl"),
                               "dataset_revision": revision, "options": choices, "image_refs": image_refs, "paper_validation": validation, "topic_tags": tags,
                               "answer_match": "matched" if len(matches) == 1 and answer else "missing" if not answer else "provided",
                               "original_answer_record": matches[0] if len(matches) == 1 else None})
