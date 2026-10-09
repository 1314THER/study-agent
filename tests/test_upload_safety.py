"""Uploads stay inside their temporary directory and enforce a per-file limit."""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

import backend.main as main


class UploadSafetyTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_names_cannot_overwrite_files_outside_temp_directory(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            outside = root_path / "outside.png"
            outside.write_bytes(b"original")
            for endpoint, expected_name in (
                (main.api_multimodal_parse, "upload.png"),
                (main.api_ocr_answer, "answer.png"),
            ):
                for filename in ("../outside.png", str(outside)):
                    with self.subTest(endpoint=endpoint.__name__, filename=filename):
                        upload_dir = root_path / "uploads"
                        upload_dir.mkdir()
                        upload = UploadFile(BytesIO(b"new image"), filename=filename)

                        def inspect_upload(path, *_args):
                            self.assertEqual(Path(path), upload_dir / expected_name)
                            self.assertEqual(Path(path).read_bytes(), b"new image")
                            return [] if endpoint is main.api_multimodal_parse else {"text": "ok"}

                        downstream = (
                            "backend.main.parse_file"
                            if endpoint is main.api_multimodal_parse
                            else "backend.multimodal.recognize_answer_image"
                        )
                        with patch("tempfile.mkdtemp", return_value=str(upload_dir)), patch(
                            downstream, side_effect=inspect_upload
                        ) as processor:
                            await endpoint(upload)
                            processor.assert_called_once()
                        self.assertEqual(outside.read_bytes(), b"original")
                        self.assertFalse(upload_dir.exists())
                        await upload.close()

    async def test_oversize_files_are_rejected_before_processing_and_cleaned_up(self):
        for endpoint, downstream in (
            (main.api_multimodal_parse, "backend.main.parse_file"),
            (main.api_ocr_answer, "backend.multimodal.recognize_answer_image"),
        ):
            with self.subTest(endpoint=endpoint.__name__):
                with tempfile.TemporaryDirectory() as root:
                    upload_dir = Path(root) / "uploads"
                    upload_dir.mkdir()
                    upload = UploadFile(BytesIO(b"x" * (16 * 1024 * 1024 + 1)), filename="image.png")
                    with patch("tempfile.mkdtemp", return_value=str(upload_dir)), patch(downstream) as processor:
                        with self.assertRaises(HTTPException) as error:
                            await endpoint(upload)
                        self.assertEqual(error.exception.status_code, 413)
                        processor.assert_not_called()
                    self.assertFalse(upload_dir.exists())
                    await upload.close()

    async def test_limit_size_file_remains_accepted(self):
        upload = UploadFile(BytesIO(b"x" * (16 * 1024 * 1024)), filename="questions.txt")
        with patch("backend.main.parse_file", return_value=[]) as processor:
            result = await main.api_multimodal_parse(upload)
            self.assertEqual(result, {"questions": [], "total": 0})
            processor.assert_called_once()
        await upload.close()


if __name__ == "__main__":
    unittest.main()
