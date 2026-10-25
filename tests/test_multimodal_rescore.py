"""multimodal.py 文件解析/DeepSeek 调用与 rescore_questions.py 测试。"""

import base64
import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import backend.multimodal as mm
from backend.multimodal import (
    _call_multimodal_model,
    _read_extraction_prompt,
    docx_to_text,
    file_to_base64,
    image_to_base64,
    parse_file,
    pdf_to_images,
    recognize_answer_image,
    resolve_multimodal_model,
)
from backend.rescore_questions import _clean_final, rescore_question


class MultimodalApiTest(unittest.TestCase):
    def test_multimodal_model_follows_selected_teacher(self):
        expected = {
            "liangliang": ("glm-4.6v-flash", "glm-4.7-flash"),
            "taotao": ("deepseek-flash", "deepseek-flash"),
            "xuefeng": ("glm-5.3-flash", "glm-5.3-flash"),
            "ji": ("gpt-6-astra", "gpt-6-astra"),
        }
        for teacher, (image_model, text_model) in expected.items():
            with self.subTest(teacher=teacher):
                self.assertEqual(resolve_multimodal_model(teacher, has_image=True)[0], image_model)
                self.assertEqual(resolve_multimodal_model(teacher, has_image=False)[0], text_model)

    def test_multimodal_call_passes_selected_model_effort_and_image_to_solver(self):
        limits = {"multimodal_max_tokens": 1200, "multimodal_timeout_seconds": 9}
        with patch.object(mm.runtime_settings, "get_limits", return_value=limits), \
                patch("backend.solver.call_deepseek", return_value=("识别结果", {})) as call:
            result = _call_multimodal_model(image_base64="YWJj", text="识别公式", teacher="ji")
        self.assertEqual(result, "识别结果")
        self.assertEqual(call.call_args.kwargs["model"], "gpt-6-astra")
        self.assertEqual(call.call_args.kwargs["reasoning_effort"], "medium")
        self.assertEqual(call.call_args.kwargs["max_tokens"], 1200)
        self.assertEqual(call.call_args.kwargs["timeout_seconds"], 9)
        self.assertEqual(call.call_args.kwargs["image_content"][0]["image_url"]["url"], "data:image/png;base64,YWJj")

    def test_multimodal_call_rejects_invalid_or_oversized_image_before_provider(self):
        with patch.object(mm.runtime_settings, "get_limits", return_value={}), \
                patch("backend.solver.call_deepseek") as call:
            with self.assertRaises(ValueError):
                _call_multimodal_model(image_base64="not-base64")
            with patch.object(mm, "MAX_IMAGE_BYTES", 2), self.assertRaises(ValueError):
                _call_multimodal_model(image_base64="YWJj")
            call.assert_not_called()

    def test_glm46v_image_preserves_whole_frame_and_respects_dimension_limit(self):
        from PIL import Image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            Image.new("RGB", (6100, 10), "white").save(path)
            encoded = file_to_base64(path)
            fitted, mime = mm._fit_glm46v_image(encoded)
            image = Image.open(io.BytesIO(base64.b64decode(fitted)))
            self.assertEqual(mime, "image/jpeg")
            self.assertLessEqual(max(image.size), 6000)
            self.assertGreater(image.size[0], image.size[1])
        finally:
            os.unlink(path)

    def test_glm46v_keeps_jpeg_data_url_mime(self):
        from PIL import Image
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            path = f.name
        try:
            Image.new("RGB", (20, 10), "white").save(path, format="JPEG")
            encoded = file_to_base64(path)
            fitted, mime = mm._fit_glm46v_image(encoded)
            self.assertEqual(mime, "image/jpeg")
            self.assertEqual(fitted, encoded)
        finally:
            os.unlink(path)

    def test_file_base64(self):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin", delete=False) as f:
            f.write(b"abc")
            path = f.name
        try:
            self.assertEqual(file_to_base64(path), "YWJj")
            with self.assertRaises(ValueError):
                image_to_base64(path)
        finally:
            os.unlink(path)

    def test_image_preparation_preserves_whole_image_and_exif_orientation(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "camera.jpg")
            image = Image.new("RGB", (80, 40), "white")
            exif = image.getexif()
            exif[274] = 6  # Camera stores landscape pixels; display rotates 90°.
            image.save(path, exif=exif)
            normalized = Image.open(io.BytesIO(base64.b64decode(image_to_base64(path))))
            self.assertEqual(normalized.format, "PNG")
            self.assertEqual(normalized.size, (40, 80))
            self.assertNotIn(274, normalized.getexif())

            image = Image.new("RGB", (100, 50), "white")
            image.save(path)
            with patch.object(mm, "MAX_IMAGE_SIDE", 20):
                normalized = Image.open(io.BytesIO(base64.b64decode(image_to_base64(path))))
            self.assertEqual(normalized.size, (20, 10))

    def test_read_extraction_prompt(self):
        self.assertTrue(_read_extraction_prompt().strip())

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

    def test_pdf_render_respects_provider_dimension_limit(self):
        page = types.SimpleNamespace(rect=types.SimpleNamespace(width=720, height=1440))
        self.assertEqual(mm._pdf_render_scale(page, 200), 200 / 72)
        with patch.object(mm, "MAX_IMAGE_SIDE", 1000):
            self.assertEqual(mm._pdf_render_scale(page, 200), 1000 / 1440)

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
            with patch.object(mm, "_call_multimodal_model", return_value=self._llm_json()):
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
            with patch.object(mm, "iter_pdf_images", return_value=iter([(1, 1, "b64")])), \
                 patch.object(mm, "_call_multimodal_model", return_value=self._llm_json()):
                self.assertEqual(len(parse_file(pdf_path)), 1)
            with patch.object(mm, "image_to_base64", return_value="b64"), \
                 patch.object(mm, "_call_multimodal_model", return_value=self._llm_json()):
                self.assertEqual(len(parse_file(img_path)), 1)
            with patch.object(mm, "docx_to_text", return_value="题目"), \
                 patch.object(mm, "_call_multimodal_model", return_value=self._llm_json()):
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
                 patch.object(mm, "_call_multimodal_model", return_value="设 $x=1$，解得 $x=1$。这是完整作答。"):
                result = recognize_answer_image(path)
            self.assertEqual(result["confidence"], "high")

            with patch.object(mm, "image_to_base64", return_value="b64"), \
                 patch.object(mm, "_call_multimodal_model", return_value="x=1"):
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
