from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import fitz

from backend.pool_sources import iter_source_records, _record, _text_page_records
from backend.source_conversion import parse_pages, read_pdf_pages
from backend.gaokao_related import EXPECTED, validate_paper


def make_pdf(path, texts, scan_pages=()):
    with fitz.open() as document:
        for number, text in enumerate(texts, 1):
            page = document.new_page()
            if number in scan_pages:
                with fitz.open() as source:
                    src = source.new_page()
                    src.insert_text((40, 60), text, fontname="china-s", fontsize=12)
                    image = src.get_pixmap().tobytes("png")
                page.insert_image(page.rect, stream=image)
            else:
                page.insert_text((40, 60), text, fontname="china-s", fontsize=12)
        document.save(path)


class SourceConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"

    def test_paper_first_answers_and_cross_page_boundaries(self):
        pages = [(1, "2025年甲校模拟考试数学试卷\n1. 随机变量 X 的分布如下：\nX | 0 | 1\nP | 1/2 | 1/2\n2. 导数题第一行"),
                 (2, "导数题跨页条件\n参考答案\n1. 【答案】0.5\n2. 【答案】2x"),
                 (3, "2026年乙校模拟考试数学试卷\n1. 椭圆题\n参考答案\n1. 【答案】3")]
        records = [r for r in _text_page_records(pages, "book.pdf") if r["question_no"]]
        self.assertEqual([r["answer"] for r in records], ["0.5", "2x", "3"])
        self.assertIn("跨页条件", records[1]["question"])
        self.assertIn("P | 1/2 | 1/2", records[0]["question"])
        self.assertNotEqual(records[0]["raw"]["paper_id"], records[2]["raw"]["paper_id"])
        # A separate answer booklet can revisit named papers in another order.
        records = list(_text_page_records([(1, "2025年甲校模拟考试数学试卷\n1. 甲题"),
                                          (2, "2026年乙校模拟考试数学试卷\n1. 乙题"),
                                          (3, "2025年甲校模拟考试数学试卷参考答案\n1. A"),
                                          (4, "2026年乙校模拟考试数学试卷参考答案\n1. B")], "answers.pdf"))
        self.assertEqual([r["answer"] for r in records], ["A", "B"])

    def test_unexplained_reset_and_omitted_pages_do_not_merge(self):
        records = list(_text_page_records([(1, "1. 第一卷题\n2. 第一卷题二\n1. 第二卷题")], "unknown.pdf"))
        self.assertEqual(len(records), 3)
        self.assertTrue(records[-1]["raw"]["boundary_uncertain"])
        records = list(_text_page_records([(1, "1. 上页"), (3, "不明续文")], "gap.pdf"))
        self.assertNotIn("不明续文", next(r["question"] for r in records if r["question_no"] == "1"))

    def test_split_title_and_numbered_instructions_are_not_questions(self):
        records = list(_text_page_records([(1, "2026年甲校模拟考试\n数学\n注意事项：\n1. 填写姓名\n2. 使用黑色笔\n一、单项选择题\n1. 集合题\n二、多项选择题\n9. 导数题")], "book.pdf"))
        questions = [r for r in records if r["question_no"]]
        self.assertEqual([r["question_no"] for r in questions], ["1", "9"])
        self.assertEqual([r["question_type"] for r in questions], ["选择题", "多选题"])
        self.assertEqual(questions[0]["year"], 2026)
        self.assertIn("填写姓名", next(r["question"] for r in records if not r["question_no"]))

    def test_twenty_ocr_workers_obey_shared_limit(self):
        from backend.jobs import provider_slot
        path = self.root / "twenty.pdf"
        make_pdf(path, [""] * 21)
        barrier = threading.Barrier(20, timeout=5)
        lock, active, maximum = threading.Lock(), [0], [0]
        def ocr(encoded, filename, page):
            with provider_slot("deepseek"):
                with lock:
                    active[0] += 1
                    maximum[0] = max(maximum[0], active[0])
                if page <= 20:
                    barrier.wait()
                with lock:
                    active[0] -= 1
            return [_record(f"{filename}#p{page}", f"题干{page}", question_no=str(page), raw={"file": filename})]
        stats = {}
        units = read_pdf_pages(path, {"ocr_mode": "force", "dpi": 72, "cache_dir": self.cache, "stats": stats}, ocr, "prompt")
        self.assertEqual(maximum[0], 20)
        self.assertEqual(len(units), 21)
        self.assertEqual(stats["failed_pages"], 0)
        self.assertEqual(stats["concurrency"], 20)

    def test_ocr_fragments_and_footer_cannot_create_questions(self):
        path = self.root / "fragments.pdf"
        make_pdf(path, ["扫描原卷"], [1])
        response = json.dumps([
            {"question": "8. 求函数的零点", "question_no": "8", "question_type": "选择题", "section": "question"},
            {"question": "注意事项：\n1. 填写姓名\n2.选择题的作答：涂答题卡\n3.考试结束交卷", "section": "fragment"},
            {"question": "9. 选择正确选项", "question_no": "9", "question_type": "多选题", "section": "question"},
            {"question": "2026年甲校模拟考试数学试卷 第1页 共4页", "section": "fragment"},
            {"question": "12. 求随机变量的期望", "question_no": "12", "question_type": "填空题", "section": "question"}], ensure_ascii=False)
        with patch("backend.multimodal._call_deepseek_vision", return_value=response):
            records = list(iter_source_records(path, "pdf", {"ocr_mode": "auto", "questions_only": True, "cache_dir": self.cache}))
        questions = [r for r in records if r["question_no"]]
        self.assertEqual([r["question_no"] for r in questions], ["8", "9", "12"])
        self.assertEqual([r["question_type"] for r in questions], ["选择题", "多选题", "填空题"])
        self.assertEqual(len({r["raw"]["paper_id"] for r in questions}), 1)
        self.assertTrue(any("填写姓名" in r["question"] and not r["question_no"] for r in records))

    def test_damaged_text_cache_is_reclassified_without_invalidating_ocr(self):
        path = self.root / "bad-font.pdf"
        garbage = "\n".join(["! # $ % & " * 12] * 25)
        make_pdf(path, [garbage])
        stats = {}
        options = {"ocr_mode": "auto", "cache_dir": self.cache, "stats": stats}
        def ocr(*args):
            return [_record("bad-font.pdf#p1-ocr1", "完整原题", question_no="1")]
        read_pdf_pages(path, options, ocr, "prompt")
        self.assertEqual(stats["ocr_requests"], 1)
        cache_file = next(self.cache.glob("*/*/page-1.json"))
        cache_file.write_text(json.dumps({"page": 1, "status": "success", "kind": "text", "text": garbage}))
        read_pdf_pages(path, options, ocr, "prompt")
        self.assertEqual(stats["ocr_requests"], 1)
        read_pdf_pages(path, options, ocr, "prompt")
        self.assertEqual(stats["ocr_requests"], 0)
        self.assertEqual(stats["cache_hits"], 1)

    def test_printed_section_overrides_wrong_ocr_type_and_joins_options(self):
        path = self.root / "sections.pdf"
        make_pdf(path, ["第一页", "第二页"], [1, 2])
        responses = [json.dumps([
            {"question": "6. 已知函数，选择正确表达式", "question_no": "6", "question_type": "选择题", "section": "question"}], ensure_ascii=False), json.dumps([
            {"question": "A. $x$\nB. $x^2$\nC. $x^3$\nD. $x^4$", "question_no": "6", "question_type": "选择题", "section": "question"},
            {"question": "二、多项选择题：本题共3小题", "section": "fragment"},
            {"question": "11. 选择所有符合条件的选项", "question_no": "11", "question_type": "选择题", "section": "question"}], ensure_ascii=False)]
        with patch("backend.multimodal._call_deepseek_vision", side_effect=responses):
            records = list(iter_source_records(path, "pdf", {"ocr_mode": "auto", "concurrency": 1, "questions_only": True, "cache_dir": self.cache}))
        questions = [r for r in records if r["question_no"]]
        self.assertEqual([r["question_no"] for r in questions], ["6", "11"])
        self.assertIn("D. $x^4$", questions[0]["question"])
        self.assertEqual(questions[0]["page_end"], 2)
        self.assertEqual(questions[1]["question_type"], "多选题")

    def test_real_text_and_scan_off_need_no_cloud_requests(self):
        text_pdf = self.root / "text.pdf"
        make_pdf(text_pdf, ["2025年甲校模拟考试数学试卷\n1. 求函数导数\n【答案】2x"])
        scan_pdf = self.root / "scan.pdf"
        make_pdf(scan_pdf, ["1. 扫描原文"], [1])
        with patch("backend.multimodal._call_deepseek_vision") as cloud:
            text = list(iter_source_records(text_pdf, "pdf", {"ocr_mode": "auto", "cache_dir": self.cache}))
            scan = list(iter_source_records(scan_pdf, "pdf", {"ocr_mode": "off", "cache_dir": self.cache}))
        cloud.assert_not_called()
        self.assertEqual(text[0]["answer"], "2x")
        self.assertTrue(scan[0]["raw"]["scan"])

    def test_concurrency_page_order_context_and_success_cache(self):
        from backend.jobs import provider_slot
        from backend.data_paths import workspace, workspace_directory
        from backend.identity import identity_context, current_identity
        path = self.root / "scan.pdf"
        make_pdf(path, ["1. 甲", "2. 乙", "3. 丙"], [1, 2, 3])
        lock, active, maximum, calls = threading.Lock(), [0], [0], []
        def ocr(encoded, filename, page):
            self.assertEqual(workspace_directory(), str(self.root))
            self.assertEqual(current_identity()["id"], "owner")
            with provider_slot("deepseek"):
                with lock:
                    active[0] += 1
                    maximum[0] = max(maximum[0], active[0])
                    calls.append(page)
                time.sleep(.25 if page == 1 else .15)
                with lock:
                    active[0] -= 1
            return [_record(f"{filename}#p{page}-ocr1", f"第{page}页原题", "A", question_no=str(page), page_start=page, page_end=page,
                            raw={"file": filename, "ocr": {}})]
        stats = {}
        options = {"ocr_mode": "auto", "concurrency": 2, "cache_dir": self.cache, "stats": stats}
        with workspace(self.root), identity_context({"id": "owner", "role": "owner"}):
            units = read_pdf_pages(path, options, ocr, "prompt")
            self.assertEqual([u["page"] for u in units], [1, 2, 3])
            self.assertEqual(maximum[0], 2)
            self.assertEqual(stats["ocr_requests"], 3)
            read_pdf_pages(path, options, ocr, "prompt")
        self.assertEqual(len(calls), 3)
        self.assertEqual(stats["ocr_requests"], 0)
        self.assertEqual(stats["cache_hits"], 3)

    def test_failed_page_retry_and_interruption_resume(self):
        from backend.jobs import JobStopped
        path = self.root / "scan.pdf"
        make_pdf(path, ["甲", "乙", "丙"], [1, 2, 3])
        calls = []
        fail = [True]
        def ocr(encoded, filename, page):
            calls.append(page)
            if page == 2 and fail[0]:
                raise RuntimeError("模拟网络失败")
            return [_record(f"{filename}#p{page}-ocr1", f"第{page}题", "A", question_no=str(page), page_start=page, page_end=page)]
        stats = {}
        options = {"ocr_mode": "auto", "cache_dir": self.cache, "stats": stats}
        read_pdf_pages(path, options, ocr, "prompt")
        self.assertEqual(stats["failed_page_numbers"], [2])
        read_pdf_pages(path, {**options, "retry_failed": False}, ocr, "prompt")
        self.assertEqual(len(calls), 3)
        fail[0] = False
        read_pdf_pages(path, {**options, "retry_failed": True}, ocr, "prompt")
        self.assertEqual(calls, [1, 2, 3, 2])
        self.assertEqual(stats["cache_hits"], 2)
        interrupted = self.root / "interrupted"
        def cancel(stats):
            if stats["completed_pages"] == 1:
                raise JobStopped("模拟中断")
        with self.assertRaises(JobStopped):
            read_pdf_pages(path, {"ocr_mode": "auto", "concurrency": 1, "cache_dir": interrupted, "progress": cancel}, ocr, "prompt")
        self.assertEqual(calls[-1], 1)
        read_pdf_pages(path, {"ocr_mode": "auto", "concurrency": 1, "cache_dir": interrupted, "stats": stats}, ocr, "prompt")
        self.assertEqual(stats["cache_hits"], 1)
        self.assertEqual(stats["ocr_requests"], 2)

    def test_mixed_pdf_joins_ocr_continuation_with_text(self):
        path = self.root / "mixed.pdf"
        make_pdf(path, ["2026年甲校模拟考试数学试卷\n1. 随机变量 X 条件", "续文"], [2])
        response = json.dumps([{"question": r"求分布列：$\begin{array}{c|cc}X&0&1\\P&1/2&1/2\end{array}$",
                               "question_no": "1", "continuation": True, "answer": "0.5", "solution": "原解析"}], ensure_ascii=False)
        with patch("backend.multimodal._call_deepseek_vision", return_value=response) as cloud:
            records = list(iter_source_records(path, "pdf", {"ocr_mode": "auto", "cache_dir": self.cache}))
        self.assertEqual(cloud.call_count, 1)
        self.assertEqual(len(records), 1)
        self.assertIn(r"\begin{array}", records[0]["question"])
        self.assertEqual(records[0]["answer"], "0.5")
        self.assertEqual(records[0]["page_end"], 2)
        self.assertTrue(records[0]["raw"]["ocr_fragments"])

    def test_converter_resume_rebuilds_identical_output(self):
        from scripts.convert_question_sources import main
        source = self.root / "book.txt"
        source.write_text("1. 集合题【答案】2", encoding="utf-8")
        output = self.root / "output.jsonl"
        argv = ["convert", str(source), "--output", str(output), "--ocr", "off", "--cache-dir", str(self.cache)]
        with patch("sys.argv", argv), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(), 0)
            first = output.read_bytes()
            self.assertEqual(main(), 0)
        self.assertEqual(output.read_bytes(), first)
        report = json.loads(output.with_suffix(".jsonl.report.json").read_text())
        self.assertTrue(report["files"][0]["reused_file"])
        self.assertEqual(report["ocr_requests"], 0)
        self.assertEqual(parse_pages("1,3-5,3"), [1, 3, 4, 5])
        with self.assertRaises(ValueError):
            parse_pages("0-2")


class GaokaoRelatedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def paper(self, pid, year=2026, province="浙江"):
        return [{"paperId": pid, "paperTitle": f"{year}年甲校数学模拟考试", "paperUrl": f"https://example.org/{pid}",
                 "year": year, "province": province, "paperType": "高考模拟", "qNo": n,
                 "qType": qtype, "questionCount": 19, "stem": "填空 {#blank#}1{#/blank#}" if n == 12 else "求导数",
                 "options": [{"label": "A", "content": r"$\frac{1}{2}$"}], "images": ["images/q/image.png"] if n == 16 else []}
                for n, qtype in EXPECTED.items()]

    def test_whole_paper_filter_adapter_and_source_answer_matching(self):
        rows = self.paper(1) + self.paper(2, province="北京") + self.paper(3, year=2024) + self.paper(4)[:-1]
        path = self.root / "problems.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
        answer = self.root / "answers.jsonl"
        answer.write_text(json.dumps({"paperId": 1, "qNo": 1, "answer": "A", "solution": "原卷解析"}))
        report = {}
        records = list(iter_source_records(path, "jsonl", {"source_report": report, "answers_path": answer}))
        self.assertEqual(len(records), 19)
        self.assertEqual(report["selected_papers"], 1)
        self.assertEqual(len(report["invalid_papers"]), 1)
        self.assertEqual(records[0]["answer"], "A")
        self.assertIn(r"\frac{1}{2}", records[0]["question"])
        self.assertNotIn("{#blank#}", records[11]["question"])
        self.assertEqual(records[11]["answer"], "")
        self.assertTrue(records[15]["raw"]["image_refs"])
        self.assertEqual(records[15]["completeness"], "deferred_graphic")
        self.assertFalse(validate_paper(self.paper(4)[:-1])["valid"])

    def test_actual_numbers_types_override_claimed_question_count(self):
        rows = self.paper(1)
        rows[-1]["qNo"] = 18
        self.assertFalse(validate_paper(rows)["valid"])

    def test_public_snapshot_retries_only_missing_assets_and_offline_verifies_hashes(self):
        from scripts.sync_question_sources import sync
        from backend.source_conversion import file_hash
        rows = self.paper(1)
        rows[15]["images"] = ["images/q/first.png", "images/q/second.png"]
        seed = self.root / "problems.jsonl"
        seed.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        source = {"id": "test", "repository": "test/data", "url": "https://example.org/test",
                  "download_hosts": ["https://example.org"], "file": "data/jsonl/problems.jsonl",
                  "pinned_revision": "a" * 40, "pinned_sha256": file_hash(seed)}
        calls, fail = [], [True]
        def download(urls, target, expected="", image=False):
            calls.append(str(target))
            if target.name == "second.png" and fail[0]:
                raise RuntimeError("临时下载失败")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            return {"sha256": file_hash(target), "bytes": target.stat().st_size, "download_url": urls[0]}
        with patch("scripts.sync_question_sources.download", side_effect=download), redirect_stderr(io.StringIO()):
            with self.assertRaises(RuntimeError):
                sync(source, self.root, revision="pinned")
            self.assertFalse((self.root / "latest.json").exists())
            fail[0] = False
            report = sync(source, self.root, revision="pinned")
            self.assertEqual(len(calls), 3)
            self.assertEqual(report["questions"]["records"], 19)
            self.assertTrue(report["images_complete"])
            sync(source, self.root, offline=True)
            self.assertEqual(len(calls), 3)
            (self.root / "snapshots" / ("a" * 40) / "data/images/q/first.png").write_bytes(b"corrupt")
            with self.assertRaises(RuntimeError):
                sync(source, self.root, offline=True)

    def test_public_download_rejects_login_html_disguised_as_image(self):
        from scripts.sync_question_sources import download, safe_repo_path
        with patch("scripts.sync_question_sources.urlopen", return_value=io.BytesIO(b"<html>Login</html>")):
            with self.assertRaises(RuntimeError):
                download(["https://example.org/image.png"], self.root / "image.png", image=True)
        self.assertFalse((self.root / "image.png").exists())
        with self.assertRaises(ValueError):
            safe_repo_path("../../settings.json")
        rows = self.paper(1)
        rows[8]["qType"] = "single"
        self.assertFalse(validate_paper(rows)["valid"])


if __name__ == "__main__":
    unittest.main()
