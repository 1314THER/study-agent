"""multimodal.py 文件解析/Qwen 调用与 rescore_questions.py 测试。"""

import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import httpx

import backend.multimodal as mm
from backend.multimodal import (
    _call_qwen_vl,
    _get_api_key,
    _read_extraction_prompt,
    docx_to_text,
    file_to_base64,
    image_to_base64,
    parse_file,
    pdf_to_images,
    recognize_answer_image,
)
from backend.rescore_questions import _clean_final, rescore_question


class MultimodalApiTest(unittest.TestCase):
    def test_get_api_key(self):
        with patch.object(mm.runtime_settings, "get_api_key", return_value="k"):
            self.assertEqual(_get_api_key(), "k")
        with patch.object(mm.runtime_settings, "get_api_key", return_value=""):
            with self.assertRaises(ValueError):
                _get_api_key()

    def test_file_base64(self):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin", delete=False) as f:
            f.write(b"abc")
            path = f.name
        try:
            self.assertEqual(file_to_base64(path), "YWJj")
            self.assertEqual(image_to_base64(path), "YWJj")
        finally:
            os.unlink(path)

    def test_read_extraction_prompt(self):
        self.assertTrue(_read_extraction_prompt().strip())

    def _qwen_patches(self):
        return (
            patch.object(mm, "_get_api_key", return_value="k"),
            patch.object(mm.runtime_settings, "get_api", return_value={"dashscope": {"base_url": "https://x/v1"}}),
            patch.object(mm.runtime_settings, "get_limits", return_value={
                "multimodal_timeout_seconds": 5,
                "multimodal_max_tokens": 1000,
            }),
        )

    def _qwen_stack(self):
        from contextlib import ExitStack
        stack = ExitStack()
        for p in self._qwen_patches():
            stack.enter_context(p)
        return stack

    def test_call_qwen_vl_success(self):
        resp = type("R", (), {
            "status_code": 200,
            "json": lambda self: {"choices": [{"message": {"content": "ok"}}]},
        })()
        with self._qwen_stack(), patch.object(mm.httpx, "post", return_value=resp):
            self.assertEqual(_call_qwen_vl(text="hi"), "ok")

    def test_call_qwen_vl_errors(self):
        resp = type("R", (), {"status_code": 500, "text": "boom"})()
        with self._qwen_stack(), patch.object(mm.httpx, "post", return_value=resp):
            with self.assertRaises(Exception) as ctx:
                _call_qwen_vl(text="hi")
        self.assertIn("500", str(ctx.exception))

        with self._qwen_stack(), patch.object(mm.httpx, "post", side_effect=httpx.TimeoutException("t")):
            with self.assertRaises(Exception) as ctx:
                _call_qwen_vl(text="hi")
        self.assertIn("超时", str(ctx.exception))

        with self._qwen_stack(), patch.object(mm.httpx, "post", side_effect=httpx.ConnectError("c")):
            with self.assertRaises(Exception) as ctx:
                _call_qwen_vl(text="hi")
        self.assertIn("无法连接", str(ctx.exception))

    def test_pdf_to_images_with_fake_fitz(self):
        class FakePix:
            def tobytes(self, fmt):
                return b"png-bytes"

        class FakePage:
            def get_pixmap(self, matrix=None):
                return FakePix()

        class FakeDoc:
            def __init__(self, path):
                self.path = path

            def __len__(self):
                return 1

            def __getitem__(self, i):
                return FakePage()

            def close(self):
                pass

        class FakeFitz:
            Matrix = staticmethod(lambda a, b: None)

            @staticmethod
            def open(path):
                return FakeDoc(path)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            with patch.dict(sys.modules, {"fitz": FakeFitz}):
                images = pdf_to_images(path)
            self.assertEqual(images, ["cG5nLWJ5dGVz"])
        finally:
            os.unlink(path)

    def test_docx_to_text_with_fake_docx(self):
        class FakePara:
            text = "第一段"

        class FakeDoc:
            def __init__(self, path):
                self.paragraphs = [FakePara()]

        fake_docx = types.ModuleType("docx")
        fake_docx.Document = FakeDoc
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            path = f.name
        try:
            with patch.dict(sys.modules, {"docx": fake_docx}):
                self.assertEqual(docx_to_text(path), "第一段")
        finally:
            os.unlink(path)

    def _llm_json(self):
        return json.dumps([{"latex": "$x^2=1$", "difficulty": "中等"}], ensure_ascii=False)

    def test_parse_file_txt(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as f:
            f.write("1. 求 $x$")
            path = f.name
        try:
            with patch.object(mm, "_call_qwen_vl", return_value=self._llm_json()):
                questions = parse_file(path)
            self.assertEqual(questions[0]["latex"], "$x^2=1$")
        finally:
            os.unlink(path)

    def test_parse_file_pdf_image_docx(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            docx_path = f.name
        try:
            with patch.object(mm, "pdf_to_images", return_value=["b64"]), \
                 patch.object(mm, "_call_qwen_vl", return_value=self._llm_json()):
                self.assertEqual(len(parse_file(pdf_path)), 1)
            with patch.object(mm, "image_to_base64", return_value="b64"), \
                 patch.object(mm, "_call_qwen_vl", return_value=self._llm_json()):
                self.assertEqual(len(parse_file(img_path)), 1)
            with patch.object(mm, "docx_to_text", return_value="题目"), \
                 patch.object(mm, "_call_qwen_vl", return_value=self._llm_json()):
                self.assertEqual(len(parse_file(docx_path)), 1)
        finally:
            for p in (pdf_path, img_path, docx_path):
                os.unlink(p)

    def test_parse_file_unsupported(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError):
                parse_file(path)
        finally:
            os.unlink(path)

    def test_recognize_answer_image(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            with patch.object(mm, "image_to_base64", return_value="b64"), \
                 patch.object(mm, "_call_qwen_vl", return_value="设 $x=1$，解得 $x=1$。这是完整作答。"):
                result = recognize_answer_image(path)
            self.assertEqual(result["confidence"], "high")

            with patch.object(mm, "image_to_base64", return_value="b64"), \
                 patch.object(mm, "_call_qwen_vl", return_value="x=1"):
                result = recognize_answer_image(path)
            self.assertEqual(result["confidence"], "medium")
        finally:
            os.unlink(path)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError):
                recognize_answer_image(path)
        finally:
            os.unlink(path)


class RescoreTest(unittest.TestCase):
    def test_clean_final(self):
        final = {"error": "x", "formatter_note": "y", "ok": 1}
        cleaned = _clean_final(final)
        self.assertNotIn("error", cleaned)
        self.assertNotIn("formatter_note", cleaned)
        self.assertEqual(cleaned["ok"], 1)

    def test_rescore_success(self):
        final = {
            "chunk_results": [{
                "chunk_type": "大题",
                "category": {"level1": "数列"},
                "steps": [],
            }],
            "overall_difficulty": {"level": "中等"},
        }
        with patch("backend.rescore_questions.step_solver_only", return_value={
            "content": "解", "category": "数列", "token_usage": {},
        }), patch("backend.rescore_questions.step_verify_all", return_value={
            "chunk_results": [], "token_usage": {},
        }), patch("backend.rescore_questions.step_final_check", return_value=final):
            result = rescore_question("题", "大题", "liangliang")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["final"]["question_type"], "大题")

    def test_rescore_solver_error(self):
        with patch("backend.rescore_questions.step_solver_only", return_value={
            "error": "雪碧了", "detail": "不可解",
        }):
            result = rescore_question("题", "大题", "liangliang")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["rejected_reason"], "不可解")

    def test_rescore_no_chunks(self):
        with patch("backend.rescore_questions.step_solver_only", return_value={
            "content": "解", "category": "数列", "token_usage": {},
        }), patch("backend.rescore_questions.step_verify_all", return_value={
            "chunk_results": [], "token_usage": {},
        }), patch("backend.rescore_questions.step_final_check", return_value={"chunk_results": []}):
            result = rescore_question("题", "大题", "liangliang")
        self.assertEqual(result["status"], "failed")

    def test_import_mother_module(self):
        import backend.import_mother  # noqa: F401


if __name__ == "__main__":
    unittest.main()
