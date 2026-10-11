"""Public-source discovery, durable downloads, question-only OCR and pool intake."""
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import time
import threading
from urllib.parse import urljoin, urlparse

from backend.source_conversion import atomic_json, file_hash, _PDF_LOCK
from backend.source_policy import year_evidence

ROOT = Path(__file__).resolve().parent.parent
WH = "https://www.wh111.com"
SEEDS = [WH + "/shuxue/jingxuanshiti/gaozhongshuxue/" + name + "/"
         for name in ("gaosanshuxueyuekao", "gaosanshuxueqizhong", "gaosanshuxueqimo")]
TOPIC_SEEDS = [WH + "/shuxue/kejianjiaoan/gssxja/"]
TOPIC = re.compile(r"导数|概率|随机变量|分布列|数学期望")
TOPIC_BOOK = re.compile(r"专题|讲义|培优|拔高|压轴|精讲精练")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.current, self.text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = dict(attrs).get("href", "")
            self.text = []

    def handle_data(self, value):
        if self.current is not None:
            self.text.append(value)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current, "".join(self.text).strip()))
            self.current = None


def public_html(url):
    from scripts.sync_question_sources import fetch_bytes
    data = fetch_bytes(url, timeout=25)
    charset = re.search(br'charset\s*=\s*["\']?([\w-]+)', data[:5000], re.I)
    encoding = charset[1].decode("ascii") if charset else "utf-8"
    return data.decode(encoding, errors="replace")


def eligible(title, years, topics=True):
    if ("数学" not in title and not TOPIC.search(title)) or re.search(r"北京|天津|上海|初[一二三]|中考|高[一二]", title):
        return False
    if re.search(r"标答|评分标准|参考答案|答案[与及]解析", title) and not re.search(r"试[题卷]|含答案", title):
        return False
    found = {int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", title)}
    if found and (not found.intersection(years) or max(found) > max(years)):
        return False
    return (bool(found) and bool(re.search(r"高三|高考|模拟|联考|调考|供题|调研", title))) or (topics and bool(TOPIC.search(title)))


def discover_wh(years, max_pages, topics, notify, active):
    candidates, errors = {}, []
    seeds = list(SEEDS)
    if topics:
        seeds += TOPIC_SEEDS
        try:
            parser = Links()
            parser.feed(public_html(WH + "/shuxue/"))
            seeds += [urljoin(WH, u) for u, label in parser.links
                      if u.startswith("/shuxue/") and not re.search(r"/20\d{2}-\d", u)
                      and re.search(r"专题|复习|导数|概率", label)]
        except Exception as exc:
            errors.append({"url": WH + "/shuxue/", "error": str(exc)})
    for seed in dict.fromkeys(seeds):
        next_url, visited = seed, set()
        while next_url and next_url not in visited and len(visited) < max_pages:
            active()
            visited.add(next_url)
            try:
                parser = Links()
                parser.feed(public_html(next_url))
                for href, title in parser.links:
                    url = urljoin(next_url, href)
                    if urlparse(url).netloc != "www.wh111.com":
                        continue
                    if re.search(r"/20\d{2}-\d{2}-\d{2}/\d+\.html$", url) and eligible(title, set(years), topics):
                        kind = "topic" if TOPIC.search(title) or TOPIC_BOOK.search(title) else "mock"
                        if kind == "mock" or topics:
                            candidates[url] = {"url": url, "title": title, "kind": kind}
                next_url = next((urljoin(next_url, u) for u, label in parser.links if "下一页" in label), None)
            except Exception as exc:
                errors.append({"url": next_url, "error": str(exc)})
                next_url = None
            notify("discover", f"已发现 {len(candidates)} 个模考／专题题源", discovered=len(candidates))
    return list(candidates.values()), errors


def inspect_and_download(candidate, resources, active):
    from scripts.sync_question_sources import download
    active()
    key = sha256(candidate["url"].encode()).hexdigest()[:24]
    folder = resources / key
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = folder / "resource.json"
    prior = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    if prior.get("file") and (folder / prior["file"]).exists() and file_hash(folder / prior["file"]) == prior.get("sha256"):
        return {**prior, "cache_hit": True, "path": str((folder / prior["file"]).resolve())}
    html = public_html(candidate["url"])
    (folder / "source.html").write_text(html, encoding="utf-8")
    # Only follow download controls actually exposed by the public page.
    controls = re.findall(r"getDownFunc\(\d+,\s*['\"]([^'\"]+)['\"][^\n]*?\n?", html)
    if not controls:
        raise ValueError("页面没有可读取的附件下载入口")
    zero_cost = re.search(r"扣除点数\s*[：:]?\s*(?:<[^>]+>\s*)*0(?:\s*<|\s*[）)])", html)
    if not zero_cost and "免费" not in candidate["title"]:
        raise ValueError("附件未标为免费，保留题源链接")
    target = folder / "original.bin"
    data = download([urljoin(candidate["url"], controls[0])], target)
    with target.open("rb") as stream:
        head = stream.read(8)
    if head.startswith(b"%PDF-"):
        kind, name = "pdf", "original.pdf"
    elif head.startswith(b"PK\x03\x04"):
        import zipfile
        with zipfile.ZipFile(target) as archive:
            if "word/document.xml" not in archive.namelist():
                raise ValueError("取得 ZIP 合集，原文件已保留，待选择其中的题源")
        kind, name = "docx", "original.docx"
    else:
        raise ValueError("下载返回网页或不支持的文件，可能需要登录")
    final = folder / name
    target.replace(final)
    result = {**candidate, **data, "file": name, "format": kind, "cache_hit": False, "path": str(final.resolve())}
    atomic_json(manifest, result)
    return result


def convert_resource(resource, cache, concurrency, ocr, notify, active, retry_failed=True):
    from backend.pool_sources import iter_source_records
    from scripts.sync_question_sources import write_jsonl
    active()
    path = Path(resource["path"])
    stats = {}
    options = {"ocr_mode": "auto" if ocr else "off", "questions_only": True, "language": "zh", "concurrency": concurrency,
               "cache_dir": cache, "resume": True, "retry_failed": retry_failed, "stats": stats,
               "progress": lambda s: notify("ocr", "正在识别 " + resource["title"] + f"：{s['completed_pages']}/{s['total_pages']} 页，缓存 {s['cache_hits']}，失败 {s['failed_pages']}", current_pages=s["completed_pages"], current_failed=s["failed_pages"])}
    requests = 0
    if resource["format"] == "pdf":
        import fitz
        with _PDF_LOCK, fitz.open(path) as document:
            page_count = len(document)
        records = []
        # Start with four question pages; extend only when the full paper is
        # not yet present. Re-read earlier pages from cache, without new calls.
        for end in range(min(4, page_count), page_count + 4, 4):
            active()
            options["page_numbers"] = list(range(1, min(end, page_count) + 1))
            records = list(iter_source_records(path, "pdf", options))
            requests += stats.get("ocr_requests", 0)
            if resource["kind"] == "mock" and {r["question_no"] for r in records if r.get("question_no", "").isdigit()} == {str(n) for n in range(1, 20)}:
                break
            if end >= page_count:
                break
    else:
        records = list(iter_source_records(path, resource["format"], options))
    questions = [r for r in records if str(r.get("question_no", "")).isdigit() and not r["source_key"].split("#", 1)[-1].startswith("answer-")]
    expected = {n: "选择题" if n <= 8 else "多选题" if n <= 11 else "填空题" if n <= 14 else "大题" for n in range(1, 20)}
    counts = Counter(str(r["question_no"]) for r in questions)
    paper_ids = {r["raw"].get("paper_id") for r in questions}
    valid = ((resource["kind"] == "topic" and bool(questions)) or (resource["kind"] == "mock" and len(paper_ids) == 1 and not any(r["raw"].get("boundary_uncertain") for r in questions)
             and set(counts) == {str(n) for n in expected} and all(v == 1 for v in counts.values())
             and all(r["question_type"] == expected[int(r["question_no"])] for r in questions)))
    for record in records:
        record["source_key"] = resource["sha256"][:16] + "/" + record["source_key"]
        record["raw"].update(original_file=str(path), file_sha256=resource["sha256"], collection_title=resource["title"],
                             paper_url=resource["url"], collector=True, conversion_parser=4, paper_validation={"valid": valid, "actual_questions": len(questions)})
        if record["completeness"] == "deferred_graphic":
            record["raw"]["graphic_file"] = {"sha256": resource["sha256"], "page_start": record["page_start"],
                                                "page_end": record["page_end"], "question_no": record["question_no"]}
        # Preserve an actual paper heading inside a collection. A new cover
        # title must never relabel a reliably dated older paper as a new one.
        record["raw"].setdefault("paper", resource["title"])
        if record["year"] is None:
            record["year"] = year_evidence({"raw": {"paper": resource["title"]}})["year"]
        # These are question candidates; original answers are never required.
        record["answer"], record["solution"] = "", ""
    output = path.parent / "questions.jsonl"
    write_jsonl(output, records)
    return {**resource, "records": questions, "output": str(output), "valid": valid, "ocr_requests": requests,
            "question_count": len(questions), "completed_pages": stats.get("completed_pages", 0),
            "cache_page_hits": stats.get("cache_hits", 0), "failed_pages": stats.get("failed_pages", 0),
            "failed_page_numbers": stats.get("failed_page_numbers", []), "review_records": len(records) - len(questions)}


def collect(args, root, progress=None):
    """Serialize runs across the web worker and standalone agents."""
    import fcntl
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not 1 <= len(args.get("years", [])) <= 10 or any(type(y) is not int or not 2016 <= y <= 2100 for y in args["years"]):
        raise ValueError("请选择 2016 年及以后的题源年份")
    if type(args.get("max_pages", 32)) is not int or not 1 <= args.get("max_pages", 32) <= 100:
        raise ValueError("目录搜索页数应为 1 至 100")
    with (root / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("已有找题任务正在运行，请查看后台进度")
        try:
            return _collect(args, root, progress)
        except Exception as exc:
            from backend.jobs import JobStopped
            path = root / "progress.json"
            if path.exists():
                report = json.loads(path.read_text(encoding="utf-8"))
                report.update(stage="interrupted" if isinstance(exc, JobStopped) else "error", message="找题未完成：" + str(exc)[:1000])
                atomic_json(path, report)
            raise
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _collect(args, root, progress=None):
    from backend.jobs import ensure_active
    from scripts.sync_question_sources import sync, write_jsonl
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    started = time.perf_counter()
    all_questions = []
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report = {"run_id": run_id, "stage": "starting", "years": args["years"], "discovered": 0, "downloaded": 0, "cache_hits": 0,
              "converted": 0, "verified_papers": 0, "verified_topics": 0, "question_records": 0, "added_occurrences": 0, "ocr_requests": 0,
              "completed_pages": 0, "cache_page_hits": 0, "failed_pages": 0, "unverified_papers": 0,
              "solver_requests": 0, "failures": [], "resources": [], "conversion_results": [], "structured": None,
              "current_pages": 0, "current_failed": 0, "message": "", "elapsed_seconds": 0}
    progress_lock = threading.RLock()
    def notify(stage, message, **values):
        with progress_lock:
            report.update(stage=stage, message=message, elapsed_seconds=round(time.perf_counter() - started, 2), **values)
            atomic_json(root / "progress.json", report)
            if progress:
                progress(dict(report))
    notify("starting", "正在启动在线找题任务")
    if args.get("structured", True):
        notify("structured", "正在核验结构化模考题库的新版本")
        registry = json.loads((ROOT / "config/question-sources.json").read_text(encoding="utf-8"))
        source = next(s for s in registry["sources"] if s["id"] == "gaokao-related-math")
        try:
            data_root = root.parent / "sources/gaokao-related-math"
            try:
                manifest = sync(source, data_root, years=args["years"], offline=args.get("cached_only", False))
            except Exception as exc:
                if args.get("cached_only") or not (data_root / "latest.json").exists():
                    raise
                report["failures"].append({"source": "gaokao-related-math", "error": "最新版本暂时不可读取，复用已验证的本地快照：" + str(exc)})
                manifest = sync(source, data_root, years=args["years"], offline=True)
            pointer = json.loads((data_root / "latest.json").read_text(encoding="utf-8"))
            with (data_root / pointer["questions"]).open(encoding="utf-8") as stream:
                records = [json.loads(line) for line in stream]
            all_questions.extend(records)
            report["question_records"] += len(records)
            if args.get("import_pool", True):
                from contextlib import closing
                from backend.question_pool import import_records, _connection
                with closing(_connection()) as conn:
                    existing = conn.execute("SELECT id FROM pool_sources WHERE kind='gaokao_related' AND url=? AND revision=? ORDER BY id LIMIT 1", (source["url"], manifest["revision"])).fetchone()
                identity = existing["id"] if existing else {"name": "公开结构化模考 " + "/".join(map(str, args["years"])), "kind": "gaokao_related",
                                                            "url": source["url"], "revision": manifest["revision"], "publication_allowed": False}
                result = import_records(identity, records, retry_failed=True)
                report["added_occurrences"] += result["added_occurrences"]
            report["structured"] = {"revision": manifest["revision"], "papers": manifest["source_report"]["selected_papers"], "records": len(records)}
        except Exception as exc:
            report["failures"].append({"source": "gaokao-related-math", "error": str(exc)})
    if args.get("cached_only"):
        candidates, errors = [], []
        discovery_path = root / "discovery-report.json"
        if discovery_path.exists():
            discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
            if sorted(discovery.get("years", [])) == sorted(args["years"]):
                report["discovery"] = {"run_id": discovery.get("run_id"), "discovered": discovery["discovered"], "from_cache": True}
                report["failures"].extend(discovery.get("failures", []))
    else:
        candidates, errors = discover_wh(args["years"], args.get("max_pages", 32), args.get("topics", True), notify, ensure_active)
    report["failures"].extend(errors)
    resources = root / "resources"
    ready = []
    if args.get("cached_only"):
        for manifest_path in resources.glob("*/resource.json"):
            resource = json.loads(manifest_path.read_text(encoding="utf-8"))
            file = manifest_path.parent / resource["file"]
            if eligible(resource["title"], set(args["years"]), args.get("topics", True)) and file.exists() and file_hash(file) == resource["sha256"]:
                ready.append({**resource, "cache_hit": True, "path": str(file.resolve())})
        report["discovered"] = report["downloaded"] = report["cache_hits"] = len(ready)
        report["resources"] = list(ready)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(copy_context().run, inspect_and_download, candidate, resources, ensure_active): candidate for candidate in candidates}
        for future in as_completed(futures):
            ensure_active()
            candidate = futures[future]
            try:
                resource = future.result()
                ready.append(resource)
                report["downloaded"] += 1
                report["cache_hits"] += int(resource["cache_hit"])
                report["resources"].append(resource)
            except Exception as exc:
                report["failures"].append({**candidate, "error": str(exc)})
            notify("download", f"已取得 {len(ready)}/{len(candidates)} 份题源文件")
    if not args.get("cached_only"):
        atomic_json(root / "discovery-report.json", {"run_id": run_id, "years": args["years"], "discovered": len(candidates),
                    "downloaded": len(ready), "failures": list(report["failures"])})
    if args.get("convert", True):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(copy_context().run, convert_resource, r, root.parent / "conversion-cache",
                                       args.get("concurrency", 20), args.get("ocr", True), notify, ensure_active,
                                       args.get("retry_failed", True)): r for r in ready}
            for future in as_completed(futures):
                ensure_active()
                resource = futures[future]
                try:
                    converted = future.result()
                    records = converted.pop("records")
                    all_questions.extend(records)
                    report["converted"] += 1
                    report["ocr_requests"] += converted["ocr_requests"]
                    report["verified_papers"] += int(converted["valid"] and resource["kind"] == "mock")
                    report["verified_topics"] += int(converted["valid"] and resource["kind"] == "topic")
                    report["unverified_papers"] += int(not converted["valid"])
                    for field in ("completed_pages", "cache_page_hits", "failed_pages"):
                        report[field] += converted[field]
                    report["question_records"] += len(records)
                    if converted["valid"] and args.get("import_pool", True):
                        from backend.question_pool import create_source, import_records, files_directory
                        token = resource["sha256"] + "." + resource["format"]
                        files = files_directory()
                        files.mkdir(parents=True, exist_ok=True, mode=0o700)
                        target = files / token
                        if not target.exists():
                            shutil.copyfile(resource["path"], target)
                            target.chmod(0o600)
                        sid = create_source({"name": resource["title"], "kind": resource["format"], "url": resource["url"],
                                             "revision": resource["sha256"], "file_token": token, "filename": Path(resource["path"]).name,
                                             "publication_allowed": False, "options": {"ocr": args.get("ocr", True), "questions_only": True, "concurrency": args.get("concurrency", 20)}})
                        result = import_records(sid, records, retry_failed=True)
                        report["added_occurrences"] += result["added_occurrences"]
                    report.setdefault("conversion_results", []).append(converted)
                except Exception as exc:
                    report["failures"].append({**resource, "error": str(exc)})
                notify("convert", f"已转换 {report['converted']}/{len(ready)} 份；采集 {report['question_records']} 条题目")
    if args.get("convert", True) or (report["structured"] and not (root / "collected-questions.jsonl").exists()):
        write_jsonl(root / "collected-questions.jsonl", all_questions)
        write_jsonl(root / "derivative-candidates.jsonl", [r for r in all_questions if "函数与导数" in r["categories"]])
        write_jsonl(root / "probability.jsonl", [r for r in all_questions if "概率统计" in r["categories"]])
        write_jsonl(root / "comprehensive-probability.jsonl", [r for r in all_questions if "概率统计" in r["categories"] and r["question_type"] == "大题"])
    notify("done", f"采集完成：{report['downloaded']} 份文件，{report['question_records']} 条题目；新出处 {report['added_occurrences']}")
    atomic_json(root / "collection-report.json", report)
    atomic_json(root / "reports" / (run_id + ".json"), report)
    return report
