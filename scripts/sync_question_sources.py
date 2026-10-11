"""Fetch versioned public question data and images, emit offline-readable JSONL.

No login, solver, or OCR. Failed updates never replace the last good snapshot.
See docs/question-pool-agent-guide.md for downstream import and PDF conversion.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.source_conversion import atomic_json, file_hash


def fetch_bytes(url, timeout=15):
    request = Request(url, headers={"User-Agent": "study-agent-question-sources/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def download(urls, target, expected="", image=False):
    errors = []
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for url in urls:
        temp = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            request = Request(url, headers={"User-Agent": "study-agent-question-sources/1.0"})
            with urlopen(request, timeout=30) as response, temp.open("xb") as stream:
                temp.chmod(0o600)
                shutil.copyfileobj(response, stream)
            digest = file_hash(temp)
            if not temp.stat().st_size or (expected and digest != expected):
                raise ValueError("文件为空或 SHA256 与固定版本不符")
            if image:
                with temp.open("rb") as stream:
                    head = stream.read(16)
                if not (head.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8")) or head[:4] == b"RIFF"):
                    raise ValueError("附件没有合法的图片文件头，可能返回了网页")
            temp.replace(target)
            return {"sha256": digest, "bytes": target.stat().st_size, "download_url": url}
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
        finally:
            if temp.exists():
                temp.unlink()
    raise RuntimeError("；".join(errors))


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            temp.chmod(0o600)
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def safe_repo_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("数据集附件路径不安全：" + value)
    return str(path)


def sync(source, root, *, revision="latest", years=(2025, 2026), images=True, concurrency=8, offline=False):
    from backend.gaokao_related import iter_gaokao_related
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    hosts = list(source["download_hosts"])
    metadata = {}
    if offline:
        if revision == "latest":
            revision = json.loads((root / "latest.json").read_text(encoding="utf-8"))["revision"]
    elif revision == "latest":
        errors = []
        for host in hosts:
            try:
                metadata = json.loads(fetch_bytes(host + "/api/datasets/" + source["repository"]))
                revision = metadata["sha"]
                hosts = [host] + [h for h in hosts if h != host]
                break
            except Exception as exc:
                errors.append(f"{host}: {type(exc).__name__}: {exc}")
        else:
            raise RuntimeError("无法核验最新版本；未覆盖已有快照。可用 --revision pinned 或 --offline。" + "；".join(errors))
    if revision == "pinned":
        revision = source["pinned_revision"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("版本必须为 latest、pinned 或 40 位提交哈希")
    snapshot = root / "snapshots" / revision
    snapshot.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous_path = snapshot / "acquisition-manifest.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
    raw = snapshot / source["file"]
    expected = source.get("pinned_sha256", "") if revision == source["pinned_revision"] else previous.get("data", {}).get("sha256", "")
    data = previous.get("data", {})
    if not raw.exists() or (expected and file_hash(raw) != expected):
        # Reuse the already verified first acquisition without another transfer.
        legacy = root / "problems.jsonl"
        if expected and legacy.exists() and file_hash(legacy) == expected:
            raw.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(legacy, raw)
            raw.chmod(0o600)
            data = {"sha256": expected, "bytes": raw.stat().st_size, "reused_local": True}
        elif offline:
            raise ValueError("本地题干文件缺失或哈希不符")
        else:
            urls = [h + "/datasets/" + source["repository"] + "/resolve/" + revision + "/" + source["file"] for h in hosts]
            data = download(urls, raw, expected)
    data = {**data, "sha256": file_hash(raw), "bytes": raw.stat().st_size, "path": source["file"]}
    if metadata:
        atomic_json(snapshot / "dataset-info.json", metadata)
    source_report = {}
    records = list(iter_gaokao_related(raw, {"dataset_revision": revision, "mock_years": list(years), "source_report": source_report}))
    if not records or any(not r.get("question") or r.get("completeness") == "failed" for r in records):
        raise ValueError("题源为空或格式异常；保留原始下载文件，未替换最新入口")
    needed = {safe_repo_path(ref["repo_path"]) for r in records for ref in r["raw"]["image_refs"]}
    siblings = {s["rfilename"] for s in metadata.get("siblings", [])}
    if siblings and not needed.issubset(siblings):
        raise ValueError("题干引用的附件不在上游文件索引中，需核对路径")
    assets_path = snapshot / "assets-manifest.json"
    assets = json.loads(assets_path.read_text(encoding="utf-8")) if assets_path.exists() else {}
    missing = []
    for path in sorted(needed):
        target = snapshot / path
        if not (path in assets and target.exists() and file_hash(target) == assets[path].get("sha256")):
            missing.append(path)
    failures = {}
    if images and missing and not offline:
        def get_asset(path):
            urls = [h + "/datasets/" + source["repository"] + "/resolve/" + revision + "/" + quote(path, safe="/") for h in hosts]
            return download(urls, snapshot / path, image=True)
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(get_asset, path): path for path in missing}
            for count, future in enumerate(as_completed(futures), 1):
                path = futures[future]
                try:
                    assets[path] = future.result()
                except Exception as exc:
                    failures[path] = str(exc)
                atomic_json(assets_path, assets)
                if count % 20 == 0 or count == len(futures):
                    print(f"附件 {count}/{len(futures)}，失败 {len(failures)}", file=sys.stderr, flush=True)
    elif images and missing:
        failures = {path: "本地附件缺失或哈希不符" for path in missing}
    for record in records:
        record["raw"].update(original_file=str(raw.resolve()), file_sha256=data["sha256"])
        record["raw"]["image_assets"] = [{"path": ref["repo_path"], **assets[ref["repo_path"]]}
                                         for ref in record["raw"]["image_refs"] if ref["repo_path"] in assets and ref["repo_path"] not in failures]
    questions = snapshot / "questions.jsonl"
    write_jsonl(questions, records)
    derivative = [r for r in records if "函数与导数" in r["categories"] or "导数" in r["raw"]["topic_tags"]]
    probability = [r for r in records if "概率统计" in r["categories"] or "概率统计" in r["raw"]["topic_tags"]]
    write_jsonl(snapshot / "topics/derivative-candidates.jsonl", derivative)
    write_jsonl(snapshot / "topics/probability.jsonl", probability)
    write_jsonl(snapshot / "topics/comprehensive-probability-candidates.jsonl", [r for r in probability if "综合概率候选" in r["raw"]["topic_tags"]])
    manifest = {"version": 1, "source_id": source["id"], "url": source["url"], "revision": revision,
                "checked_at": datetime.now(timezone.utc).isoformat(), "upstream_updated_at": metadata.get("lastModified") or previous.get("upstream_updated_at"),
                "data": data, "years": list(years), "answers_required": False, "solver_requests": 0, "ocr_requests": 0,
                "source_report": source_report, "questions": {"path": "questions.jsonl", "sha256": file_hash(questions), "records": len(records)},
                "topic_counts": {"function_derivative_candidates": len(derivative), "probability": len(probability),
                                 "comprehensive_probability_candidates": sum("综合概率候选" in r["raw"]["topic_tags"] for r in probability)},
                "images_required": len(needed), "images_downloaded": len(needed) - len(failures) if images else len(needed) - len(missing),
                "image_failures": failures, "images_complete": images and not failures,
                "completeness": dict(Counter(r["completeness"] for r in records))}
    atomic_json(previous_path, manifest)
    if failures:
        raise RuntimeError(f"{len(failures)} 个附件失败；成功附件已缓存，重复命令会只重试失败项，latest.json 未更新")
    atomic_json(root / "latest.json", {"revision": revision, "snapshot": str(snapshot.relative_to(root)),
                                      "questions": str(questions.relative_to(root)), "images_complete": manifest["images_complete"],
                                      "manifest": str(previous_path.relative_to(root))})
    return manifest


def main():
    parser = argparse.ArgumentParser(description="获取公开题库、固定版本与附件；不解题、不调用 OCR")
    parser.add_argument("--registry", type=Path, default=ROOT / "config/question-sources.json")
    parser.add_argument("--source", default="gaokao-related-math")
    parser.add_argument("--root", type=Path, default=ROOT / ".runtime/question-pool/sources/gaokao-related-math")
    parser.add_argument("--revision", default="latest")
    parser.add_argument("--years", type=int, nargs="+", default=[2025, 2026])
    parser.add_argument("--no-images", dest="images", action="store_false", default=True)
    parser.add_argument("--concurrency", type=int, choices=range(1, 21), default=8, help="下载并发，与 OCR 并发独立")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        registry = json.loads(args.registry.read_text(encoding="utf-8"))
        source = next(s for s in registry["sources"] if s["id"] == args.source)
        if source.get("strategy") != "huggingface_jsonl":
            parser.error("该来源只登记了入口，尚不支持自动同步；请按 agent 指南获取")
        report = sync(source, args.root, revision=args.revision, years=args.years, images=args.images,
                      concurrency=args.concurrency, offline=args.offline)
        print(json.dumps({k: v for k, v in report.items() if k != "source_report"}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"同步失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
