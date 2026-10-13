"""Backfill original diagrams in the existing pool; never solve or publish.

Run with --apply to save metadata and restore diagram candidates. Original
images from the registered compilation revision are downloaded unless --offline.
Database backups and a machine-readable report accompany every applied run.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import question_pool as pool
from backend.pool_sources import compilation_images, _tex_text, _environment
from backend.question_assets import has_pool_graphics, pool_asset_data
from backend.source_conversion import atomic_json


def download_figure(directory, path, revision):
    """Cache only registered upstream raster assets, with a verified PNG body."""
    from PIL import Image
    target = directory / path
    if target.is_file():
        with Image.open(target) as image:
            image.verify()
        return {"path": path, "sha256": sha256(target.read_bytes()).hexdigest(), "cached": True}
    url = "https://raw.githubusercontent.com/DxAThing/Gaokao-Math-Problems-Compilation/" + revision + "/" + path
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=40) as response:
                data = response.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024:
                raise ValueError("原图超过大小限制")
            with Image.open(BytesIO(data)) as image:
                image.verify()
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = target.with_suffix(target.suffix + ".part")
            temp.write_bytes(data)
            temp.chmod(0o600)
            temp.replace(target)
            return {"path": path, "sha256": sha256(data).hexdigest(), "url": url, "cached": False}
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError(str(last))


def backfill(*, apply=False, offline=False, concurrency=8):
    pool._require_owner()
    directory = pool.files_directory().parent
    report_dir = directory / "image-backfill" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {"apply": apply, "offline": offline, "restored": 0, "updated": 0, "preserved_edits": 0,
              "downloaded": 0, "cached": 0, "download_failures": [], "missing_items": [], "solver_requests": 0, "ocr_requests": 0}
    with closing(pool._connection()) as conn:
        if apply:
            backup_path = report_dir / "question_pool.before.db"
            with sqlite3.connect(backup_path) as backup:
                conn.backup(backup)
            report["backup"] = str(backup_path.resolve())
        sources = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM pool_sources")}
        rows = conn.execute("SELECT * FROM pool_occurrences ORDER BY id").fetchall()
        enriched, wanted = {}, {}
        for row in rows:
            raw = pool._load(row["raw_json"], {})
            source = sources[row["source_id"]]
            if source["kind"] == "compilation" and source["url"].startswith("https://github.com/DxAThing/Gaokao-Math-Problems-Compilation/"):
                base = directory / "sources" / "compilation-20261004"
                stem = _environment(raw.get("source_text", ""), "problem")
                refs = compilation_images(_tex_text(stem or row["original_question"], figures=False))
                if refs:
                    for ref in refs:
                        path = ref["path"]
                        if path.startswith("img_repaint/") and path.endswith(".tex"):
                            ref["original_tex_path"] = path
                            ref["path"] = "img/" + path[len("img_repaint/"):-4] + ".png"
                        p = Path(ref["path"])
                        if p.is_absolute() or ".." in p.parts or not ref["path"].startswith("img/"):
                            raise ValueError("不安全的题图路径")
                        wanted[(str(base), ref["path"], source["revision"])] = True
                    raw.update(source_root=str(base.resolve()), image_refs=refs)
            elif source["kind"] == "gaokao_related" and raw.get("image_refs"):
                # Older entries predate the versioned local snapshot locator.
                base = directory / "sources" / "gaokao-related-math"
                latest = base / "latest.json"
                if latest.is_file():
                    revision = raw.get("dataset_revision") or json.loads(latest.read_text())["revision"]
                    snapshot = base / "snapshots" / revision
                    raw.setdefault("original_file", str((snapshot / "data/jsonl/problems.jsonl").resolve()))
            enriched[row["id"]] = raw
        downloads = {}
        if not offline:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(download_figure, Path(base), path, revision): (base, path) for base, path, revision in wanted}
                for index, future in enumerate(as_completed(futures), 1):
                    base, path = futures[future]
                    try:
                        result = future.result()
                        downloads[(base, path)] = result
                        report["cached" if result["cached"] else "downloaded"] += 1
                    except Exception as exc:
                        report["download_failures"].append({"path": path, "error": str(exc)})
                    if index % 50 == 0 or index == len(futures):
                        print(f"原图 {index}/{len(futures)}，失败 {len(report['download_failures'])}", flush=True)
            atomic_json(report_dir / "downloads.json", list(downloads.values()))
        items = conn.execute("SELECT * FROM pool_items ORDER BY id").fetchall()
        occurrences = {}
        for row in rows:
            origin = dict(row)
            origin["raw"] = enriched[row["id"]]
            occurrences.setdefault(row["item_id"], []).append(origin)
        for index, row in enumerate(items, 1):
            item = {**dict(row), "occurrences": occurrences.get(row["id"], [])}
            if not has_pool_graphics(item):
                continue
            data = pool_asset_data(item)
            complete = bool(data["assets"]) and not data["missing"]
            if not complete:
                report["missing_items"].append({"id": row["id"], "missing": data["missing"]})
            for origin in item["occurrences"]:
                raw = origin["raw"]
                if raw.get("question_assets") == data:
                    continue
                raw["question_assets"] = data
                if apply:
                    conn.execute("UPDATE pool_occurrences SET raw_json=? WHERE id=?", (pool._dump(raw), origin["id"]))
            can_edit = row["status"] == "unreviewed" and (row["version"] == 1 or any(
                o["raw"].get("automatic_repair_version") == row["version"] for o in item["occurrences"]))
            if not can_edit:
                report["preserved_edits"] += 1
                continue
            completeness, reason, question = row["completeness"], row["reason"], row["question"]
            if complete and completeness == "deferred_graphic":
                completeness = "needs_review"
                reason = reason.replace("题干引用图形信息，本阶段暂缓，保留出处", "原题图已加载，请核对题干与图形")
                if "已加载" not in reason:
                    reason += "；原题图已加载，请核对题干与图形"
                report["restored"] += 1
            if any(sources[o["source_id"]]["kind"] == "compilation" for o in item["occurrences"]):
                from backend.pool_sources import _figure_text
                question = _figure_text(question)
            if (question, completeness, reason) != (row["question"], row["completeness"], row["reason"]):
                report["updated"] += 1
                if apply:
                    conn.execute("UPDATE pool_items SET question=?,completeness=?,reason=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                 (question, completeness, reason, row["id"]))
                    for origin in item["occurrences"]:
                        origin["raw"]["automatic_repair_version"] = row["version"] + 1
                        conn.execute("UPDATE pool_occurrences SET raw_json=? WHERE id=?", (pool._dump(origin["raw"]), origin["id"]))
            if index % 500 == 0:
                if apply:
                    conn.commit()
                print(f"已检查至题目 {index}/{len(items)}，恢复 {report['restored']}", flush=True)
        if apply:
            conn.commit()
        report["states"] = dict(conn.execute("SELECT completeness,count(*) FROM pool_items GROUP BY completeness"))
    report["report"] = str((report_dir / "report.json").resolve())
    atomic_json(report_dir / "report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("missing_items", "download_failures")}, ensure_ascii=False, indent=2))
    print("仍缺图：", len(report["missing_items"]), "；下载失败：", len(report["download_failures"]))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--concurrency", type=int, choices=range(1, 21), default=8)
    args = parser.parse_args()
    backfill(apply=args.apply, offline=args.offline, concurrency=args.concurrency)
