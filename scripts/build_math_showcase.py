#!/usr/bin/env python3
"""Prepare public, read-only data for math.150.chat without model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend" / "showcase"
OUTPUT = ROOT / "frontend" / "math-showcase"


def load(name: str):
    return json.loads((SOURCE / name).read_text(encoding="utf-8"))


def digest(value) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def public_step(step: dict) -> dict:
    """Select only evidence shown by the page; omit request IDs and runtime data."""
    return {key: step.get(key) for key in (
        "step_number", "title", "status", "comment", "error_detail", "answer_evidence", "cause_confidence"
    )}


def build_data() -> dict:
    data = load("data.json")
    recordings = load("recordings.json")
    example = next(row for row in data["examples"] if row["id"] == "national-2023-q17")
    diagnosis = recordings["cases"][0]
    grade = diagnosis["system"]
    grade_steps = grade["structured"].get("step_results", [])
    teaching = recordings["teaching"]
    frames = []
    for index, frame in enumerate(teaching.get("frames", [])):
        structured = frame.get("structured") or {}
        frames.append({
            "index": index + 1,
            "input": frame.get("input"),
            "output": structured.get("message") or frame.get("output") or "",
            "action": structured.get("action"),
            "current_step": structured.get("current_step"),
            "total_steps": structured.get("total_steps"),
        })
    hint = next((frame for frame in frames if frame["input"] == "请给我提示"), None)
    hint_text = hint["output"] if hint else ""
    generation = recordings["generation"]
    generated_steps = generation.get("answer_json", {}).get("chunk_results", [])
    generated_steps = generated_steps[0].get("steps", []) if generated_steps else []
    comparisons = []
    for key, label in (("basic", "常见使用方式"), ("same_information", "同信息条件")):
        record = diagnosis.get(key) or {}
        comparisons.append({"label": label, "status": record.get("status"), "content": record.get("content") or ""})
    return {
        "schema_version": 1,
        "case": {
            "title": example.get("label") or "2023 新课标全国Ⅰ卷 · 第 17 题",
            "question": example["question"],
            "student_answer": diagnosis["student_answer"],
            "expected_answer": grade["structured"].get("expected_answer"),
            "source_kind": "构造的测试作答",
            "execution_origin": recordings["provenance"].get("execution_origin"),
            "diagnosis": {
                "is_correct": grade["structured"].get("is_correct"),
                "result_matched": grade["structured"].get("result_matched"),
                "steps": [public_step(step) for step in grade_steps[:2]],
            },
            "comparisons": comparisons,
            "teaching": {
                "frames": frames,
                "hint_incomplete": bool(hint and hint_text.count("$") % 2 == 1),
                "stop_step": (frames[-1].get("current_step"), frames[-1].get("total_steps")) if frames else None,
            },
            "generation": {
                "question": generation.get("question"),
                "accepted": bool(generation.get("structured", {}).get("accepted")),
                "reference_question": generation.get("reference_question"),
                "steps": [{"title": step.get("title"), "writing": step.get("standard_writing")} for step in generated_steps],
                "candidate_count": len(generation.get("structured", {}).get("candidates", [])),
                "source_did_not_use_student_errors": True,
            },
        },
        "provenance": {
            "recorded": recordings["provenance"].get("recorded_at"),
            "source_commit": recordings["provenance"].get("source_commit"),
            "input_is_constructed": True,
            "does_not_establish_learning_gain": True,
        },
    }


def build_topics() -> dict:
    research = load("research-content.json")
    vision = load("vision-content.json")
    chapter_fields = (
        "id", "title", "thesis", "body", "mechanism", "status",
        "research", "details", "pain", "bridge",
    )
    vision_fields = (
        "title", "status", "headline", "subtitle", "intro", "scope", "social_goal",
        "status_legend", "groups", "examples", "principles", "social_mechanism", "evaluation",
        "policies", "cost_estimate",
    )
    highlight_source = research.get("highlights", {})
    highlight_fields = ("label", "title", "subtitle", "manifesto", "manifesto_en", "points")
    return {
        "schema_version": 1,
        "updated_at": research.get("updated_at"),
        "title": research.get("title"),
        "primary_case": research.get("primary_case"),
        "scope": research.get("scope"),
        "chapters": [{key: row.get(key) for key in chapter_fields} for row in research.get("chapters", [])],
        "highlights": {key: highlight_source.get(key) for key in highlight_fields},
        "vision": {key: vision.get(key) for key in vision_fields},
    }


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 math.150.chat 静态数据，不调用 AI")
    parser.add_argument("--check", action="store_true", help="检查已生成文件是否与源记录一致")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    expected = {
        "math-case.json": build_data(),
        "math-topics.json": build_topics(),
    }
    if args.check:
        missing = []
        for name, value in expected.items():
            path = OUTPUT / name
            if not path.is_file():
                missing.append(name)
                continue
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                missing.append(name)
                continue
            if digest(current) != digest(value):
                missing.append(name)
        if missing:
            print("需要重新生成：" + ", ".join(missing))
            return 1
        print("math.150.chat 静态数据与公开来源一致。")
        return 0
    for name, value in expected.items():
        write_json(OUTPUT / name, value)
    print("已更新 frontend/math-showcase/math-case.json 与 math-topics.json。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
