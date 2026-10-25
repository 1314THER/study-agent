import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.question_source_collector import collect, discover_wh, eligible, inspect_and_download, SEEDS


class QuestionSourceCollectorTests(unittest.TestCase):
    def test_resource_ocr_uses_the_selected_teacher(self):
        import fitz
        from backend.question_source_collector import convert_resource
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "scan.pdf"
            with fitz.open() as document:
                document.new_page()
                document.save(file)
            resource = {"path": str(file), "format": "pdf", "kind": "topic", "title": "扫描专题"}
            with patch("backend.pool_sources.iter_source_records", return_value=[]) as read_records:
                convert_resource(resource, Path(directory) / "cache", 1, True, lambda *a, **k: None,
                                 lambda: None, teacher="ji")
            self.assertEqual(read_records.call_args.args[2]["teacher"], "ji")

    def test_cached_complete_paper_is_imported_once_without_ai(self):
        import fitz
        from backend.data_paths import workspace
        from backend.identity import identity_context
        from backend.source_conversion import file_hash, atomic_json
        with tempfile.TemporaryDirectory() as directory, workspace(directory), identity_context({"id": "studyadmin", "username": "studyadmin", "role": "owner"}):
            root = Path(directory) / "collections"
            folder = root / "resources/fixture"
            folder.mkdir(parents=True)
            file = folder / "original.pdf"
            text = ["2026年甲校高三数学模拟考试试卷"]
            for n in range(1, 20):
                if n in (1, 9, 12, 15):
                    text.append({1: "一、单项选择题", 9: "二、多项选择题", 12: "三、填空题", 15: "四、解答题"}[n])
                text.append(f"{n}. 已知函数，求导数与单调区间。")
            with fitz.open() as pdf:
                page = pdf.new_page()
                page.insert_text((40, 45), "\n".join(text), fontname="china-s", fontsize=12)
                pdf.save(file)
            atomic_json(folder / "resource.json", {"url": "https://www.wh111.com/shuxue/a/2026-05-01/1.html",
                        "title": "2026年甲校高三数学模拟考试试卷", "sha256": file_hash(file), "file": "original.pdf", "format": "pdf", "kind": "mock"})
            args = {"years": [2026], "cached_only": True, "structured": False, "concurrency": 20}
            with patch("backend.multimodal._call_multimodal_model") as ai:
                first = collect(args, root)
                second = collect(args, root)
            ai.assert_not_called()
            self.assertEqual(first["verified_papers"], 1)
            self.assertEqual(first["added_occurrences"], 19, first["failures"])
            self.assertEqual(second["added_occurrences"], 0)
            self.assertEqual(second["ocr_requests"], 0)
            self.assertEqual(second["solver_requests"], 0)
            self.assertEqual(len(list((root / "reports").glob("*.json"))), 2)

    def test_second_collector_cannot_race_the_same_workspace(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "run.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, "已有找题任务"):
                    collect({"years": [2026]}, root)

    def test_new_collection_cover_cannot_relabel_old_paper(self):
        import fitz
        from backend.data_paths import workspace
        from backend.identity import identity_context
        from backend.source_conversion import file_hash, atomic_json
        from backend.question_pool import _connection
        with tempfile.TemporaryDirectory() as directory, workspace(directory), identity_context({"id": "studyadmin", "username": "studyadmin", "role": "owner"}):
            root = Path(directory) / "collections"
            folder = root / "resources/fixture"
            folder.mkdir(parents=True)
            file = folder / "original.pdf"
            with fitz.open() as pdf:
                page = pdf.new_page()
                page.insert_text((40, 45), "2015年甲校数学模拟考试试卷\n1. 已知函数，求导数。", fontname="china-s", fontsize=12)
                pdf.save(file)
            atomic_json(folder / "resource.json", {"url": "https://www.wh111.com/shuxue/a/2026-05-01/1.html", "title": "2026届高考数学导数专题讲义", "sha256": file_hash(file), "file": "original.pdf", "format": "pdf", "kind": "topic"})
            report = collect({"years": [2026], "cached_only": True, "structured": False}, root)
            self.assertEqual(report["added_occurrences"], 0)
            with _connection() as conn:
                source_report = json.loads(conn.execute("SELECT import_report_json FROM pool_sources").fetchone()[0])
            self.assertEqual(source_report["skipped_old"], 1)
            with (folder / "questions.jsonl").open() as stream:
                records = [json.loads(line) for line in stream]
            self.assertEqual(next(r["year"] for r in records if r["question_no"]), 2015)

    def test_public_pagination_filters_years_regions_and_school_stage(self):
        first = '<a href="/shuxue/a/2026-05-01/1.html">免费 2026届高三数学模拟试卷</a><a href="index_2.html">下一页</a>'
        second = '<a href="/shuxue/a/2025-05-01/2.html">2025届高三数学导数专题</a><a href="/shuxue/a/2026-05-01/3.html">2026北京高三数学二模</a><a href="/shuxue/a/2026-05-01/4.html">2026高二数学模拟</a>'
        def html(url):
            if url.endswith('index_2.html'):
                return second
            return first if url in SEEDS else ''
        with patch('backend.question_source_collector.public_html', side_effect=html):
            candidates, errors = discover_wh([2025, 2026], 32, True, lambda *a, **k: None, lambda: None)
        self.assertEqual(len(candidates), 2)
        self.assertFalse(errors)
        self.assertFalse(eligible('2027届高三数学模拟试卷', {2025, 2026}))
        self.assertTrue(eligible('2027届高三数学模拟试卷', {2027}))
        self.assertFalse(eligible('武汉市2026届高中毕业生数学标答及评分标准', {2026}))
        self.assertTrue(eligible('2026届高考导数专题压轴题', {2026}))

    def test_free_download_is_cached_and_nonfree_page_not_fetched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = {'url': 'https://www.wh111.com/shuxue/a/2026-05-01/1.html', 'title': '2026高三数学模拟试卷', 'kind': 'mock'}
            html = "下载扣除点数：<span>0</span>）<a onclick=\"getDownFunc(0,'/e/DownSys/GetDown/?id=1',195,1,0)\">下载</a>"
            def download(urls, target):
                target.write_bytes(b'%PDF-1.3\nfixture')
                from backend.source_conversion import file_hash
                return {'sha256': file_hash(target), 'bytes': target.stat().st_size, 'download_url': urls[0]}
            with patch('backend.question_source_collector.public_html', return_value=html), patch('scripts.sync_question_sources.download', side_effect=download) as fetch:
                first = inspect_and_download(candidate, root, lambda: None)
                second = inspect_and_download(candidate, root, lambda: None)
                self.assertEqual(first['format'], 'pdf')
                self.assertTrue(second['cache_hit'])
                self.assertEqual(fetch.call_count, 1)
                candidate['url'] += '?other'
                with patch('backend.question_source_collector.public_html', return_value=html.replace('<span>0', '<span>10')):
                    with self.assertRaises(ValueError):
                        inspect_and_download(candidate, root, lambda: None)
                self.assertEqual(fetch.call_count, 1)
