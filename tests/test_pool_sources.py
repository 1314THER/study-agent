import json
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from backend.pool_sources import classify_categories, iter_source_records


class PoolSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        file = self.root / name
        file.write_text(text, encoding="utf-8")
        return file

    def test_compilation_choices_nested_math_and_private_answers(self):
        file = self.write("paper.tex", r"""\chapter{2025年全国I卷}
\section{单选题}
\begin{problem}
设集合 \(A=\{1,2\}\)，则元素个数为？
\choices{\(\frac{1}{2}\)}{\(2\)}{\(3\)}{\(4\)}
\answer{B}
\begin{solution}原解析 \(1+1=2\)\end{solution}
\end{problem}
\begin{problem}已知椭圆 \(x^2+2y^2=1\)，求焦距。\end{problem}
\begin{answer}\(\sqrt{2}\)\end{answer}
\solution{完整文字解析。}
""")
        records = list(iter_source_records(file, "compilation"))
        self.assertEqual(len(records), 2)
        self.assertIn(r"A. $\frac{1}{2}$", records[0]["question"])
        self.assertNotIn("原解析", records[0]["question"])
        self.assertNotIn(r"\answer", records[0]["question"])
        self.assertEqual(records[0]["answer"], "B")
        self.assertIn("集合与逻辑用语", records[0]["categories"])
        self.assertEqual(records[0]["year"], 2025)
        self.assertEqual(records[1]["completeness"], "complete")
        self.assertEqual(records[1]["solution"], "完整文字解析。")

    def test_graphic_triage_does_not_exclude_text_geometry(self):
        file = self.write("items.jsonl", "\n".join(json.dumps(item, ensure_ascii=False) for item in [
            {"question": "已知正方体棱长为2，求体积", "answer": "8"},
            {"question": "某几何体的三视图如图所示，求体积", "answer": "8"},
            {"question": r"函数图象大致为 \choicebitmap{A.png}", "answer": "A"},
            {"question": "求椭圆的焦点坐标", "answer": "(1,0)", "solution": r"\bitmapfigure{solution.png}"},
        ]))
        records = list(iter_source_records(file, "jsonl"))
        self.assertEqual([r["completeness"] for r in records], ["complete", "deferred_graphic", "deferred_graphic", "complete"])
        self.assertEqual(records[0]["categories"], ["立体几何"])

    def test_jsonl_invalid_and_empty_items_are_retained(self):
        file = self.write("items.jsonl", '{"question":"Q1","answer":"A"}\nnot-json\n42\n{"question":""}\n')
        records = list(iter_source_records(file, "jsonl"))
        self.assertEqual(len(records), 4)
        self.assertEqual([r["completeness"] for r in records], ["complete", "failed", "failed", "failed"])
        self.assertEqual(records[1]["raw"]["item"]["original_line"], "not-json")
        self.assertEqual([r["source_key"] for r in records], ["items.jsonl#1", "items.jsonl#2", "items.jsonl#3", "items.jsonl#4"])

    def test_highmath_and_conic_fields_preserve_originals(self):
        file = self.write("Logic_Set_Inequality_Complex.jsonl", json.dumps({"problem": "集合A有两个元素", "answer": "2", "steps": "原解析", "type": "Logic_Set_Inequality_Complex"}))
        item = next(iter_source_records(file, "highmath"))
        self.assertEqual(item["solution"], "原解析")
        self.assertEqual(item["categories"], ["集合与逻辑用语"])
        file = self.write("dev.json", json.dumps([{"text": "抛物线的焦点坐标？", "answer_expressions": "(1, 0)", "process": "原过程", "fact_expressions": "G: Parabola"}]))
        item = next(iter_source_records(file, "conic10k"))
        self.assertEqual(item["answer"], "(1, 0)")
        self.assertEqual(item["raw"]["original"]["fact_expressions"], "G: Parabola")

    def test_only_explicit_question_type_metadata_is_used(self):
        file = self.write("types.jsonl", "\n".join(json.dumps(item) for item in [
            {"problem": "Q", "answer": "A", "type": "Logic_Set_Inequality_Complex", "multiple": "", "subject": ""},
            {"problem": "Q", "answer": "AB", "multiple": "multiple_choice"},
            {"problem": "Q", "answer": "1", "subject": "填空题"},
            {"problem": "Q", "answer": "A", "question_type": "单选题"},
        ]))
        self.assertEqual([i["question_type"] for i in iter_source_records(file, "highmath")], ["", "多选题", "填空题", "选择题"])

    def test_latex_blank_and_statement_numbers_are_preserved(self):
        file = self.write("paper.tex", r"""\begin{problem}
求 \(x=\fillinblank{}\)，另一空为\fillinblank{}。
\begin{circlelist}\item 第一个条件\item 第二个条件\end{circlelist}
\end{problem}\begin{answer}1\end{answer}""")
        item = next(iter_source_records(file, "compilation"))
        self.assertIn(r"$x=\underline{\qquad}$", item["question"])
        self.assertIn("(1) 第一个条件", item["question"])
        self.assertIn("(2) 第二个条件", item["question"])

    def test_text_table_cells_are_retained(self):
        file = self.write("paper.tex", r"""\begin{problem}已知数据表：
\begin{tabular}{c|cc}项目 & \(1\) & \(2\) \\
\hline 数量 & 3 & 4\end{tabular}
\end{problem}\begin{answer}7\end{answer}""")
        item = next(iter_source_records(file, "compilation"))
        self.assertIn("项目 | $1$ | $2$", item["question"])
        self.assertIn("数量 | 3 | 4", item["question"])
        self.assertNotIn("tabular", item["question"])

    def test_compilation_loads_question_figures_with_option_labels_only(self):
        file = self.write("paper.tex", r"""\begin{problem}选择图象。
\choices{\choicebitmap{img/a.png}}{\choicebitmap{img/b.png}}{3}{4}
\FigureLayoutDeclare{img/c.png}{2cm}{0bp}
\examfiguregroup{img/c.png}{\bitmapinclude{img/c.png}\bitmapinclude{img/d.png}}
\end{problem}\begin{answer}A\end{answer}
\begin{solution}\bitmapfigure{img/solution.png}\end{solution}""")
        item = next(iter_source_records(file, "compilation"))
        self.assertEqual([r["path"] for r in item["raw"]["image_refs"]], ["img/a.png", "img/b.png", "img/c.png", "img/d.png"])
        self.assertEqual([r["label"] for r in item["raw"]["image_refs"]][:2], ["选项 A", "选项 B"])
        self.assertIn("A. [选项 A]", item["question"])
        self.assertNotIn("FigureLayoutDeclare", item["question"])
        self.assertNotIn("examfiguregroup", item["question"])

    def test_row_spacing_is_not_a_display_delimiter_and_macro_arguments_stay_grouped(self):
        file = self.write("paper.tex", r"""\begin{problem}
设 \(f(x)=\begin{cases}1,&x>0,\\[4pt]0,&x\le0\end{cases}\)。
\end{problem}\begin{answer}\(\frac1\e+\frac\e2+\bs0\)\end{answer}""")
        item = next(iter_source_records(file, "compilation"))
        self.assertIn(r"\\[4pt]", item["question"])
        self.assertNotIn(r"\$$4pt]", item["question"])
        self.assertEqual(item["question"].count("$"), 2)
        self.assertIn(r"\frac1{\mathrm{e}}", item["answer"])
        self.assertIn(r"\frac{\mathrm{e}}2", item["answer"])
        self.assertIn(r"\boldsymbol0", item["answer"])

    def test_cross_page_join_with_answer_section(self):
        file = self.write("book.txt", "1. 已知集合A=\n\f{1,2}，求元素个数。\n2. 解方程x=1。\n参考答案\n1. 【答案】2\n【解析】数元素\n2. 【答案】1")
        items = list(iter_source_records(file, "txt"))
        self.assertEqual(len(items), 2)
        self.assertIn("{1,2}", items[0]["question"])
        self.assertEqual((items[0]["page_start"], items[0]["page_end"]), (1, 2))
        self.assertEqual(items[0]["answer"], "2")
        self.assertEqual(items[0]["solution"], "数元素")
        self.assertEqual(items[0]["raw"]["answer_fragments"][0]["start"], 2)

    def test_scan_image_requires_explicit_ocr(self):
        file = self.root / "scan.png"
        file.write_bytes(b"source-image")
        with patch("backend.multimodal._call_deepseek_vision") as api:
            item = next(iter_source_records(file, "image"))
        api.assert_not_called()
        self.assertEqual(item["completeness"], "needs_review")
        self.assertTrue(item["raw"]["scan"])
        self.assertEqual(item["page_start"], 1)

    def test_docx_table_math_and_page_break(self):
        xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body>
<w:p><w:r><w:t>1. 求</w:t></w:r><m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>2</m:t></m:r></m:den></m:f></m:oMath><w:r><w:br w:type="page"/><w:t>的值。</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>【答案】0.5</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>'''
        file = self.root / "book.docx"
        with zipfile.ZipFile(file, "w") as archive:
            archive.writestr("word/document.xml", xml)
        item = next(iter_source_records(file, "docx"))
        self.assertIn(r"$\frac{1}{2}$", item["question"])
        self.assertEqual(item["answer"], "0.5")
        self.assertEqual((item["page_start"], item["page_end"]), (1, 2))

    def test_malformed_latex_keeps_item(self):
        file = self.write("bad.tex", r"\begin{problem}题干没有关闭")
        item = next(iter_source_records(file, "compilation"))
        self.assertEqual(item["completeness"], "failed")
        self.assertIn("题干没有关闭", item["raw"]["source_text"])

    def test_ocr_cross_page_continuations_keep_both_page_references(self):
        file = self.write("book.pdf", "placeholder")
        records = [
            {"source_key": "book.pdf#p1-ocr1", "question": "集合A=", "answer": "", "solution": "",
             "categories": ["集合与逻辑用语"], "question_no": "1", "page_start": 1, "page_end": 1,
             "completeness": "needs_review", "reason": "OCR 需核对", "raw": {"file": "book.pdf", "page": 1}},
            {"source_key": "book.pdf#p2-ocr1", "question": "{1,2}，求元素个数", "answer": "2", "solution": "数元素",
             "categories": [], "question_no": "1", "page_start": 2, "page_end": 2,
             "completeness": "needs_review", "reason": "OCR 需核对", "raw": {"file": "book.pdf", "page": 2, "continuation": True}},
        ]
        with patch("backend.pool_sources._read_pdf_records", return_value=iter(records)):
            items = list(iter_source_records(file, "pdf", {"ocr": True}))
        self.assertEqual(len(items), 1)
        self.assertIn("{1,2}", items[0]["question"])
        self.assertEqual(items[0]["page_end"], 2)
        self.assertEqual(items[0]["raw"]["continuation_fragments"][0]["source_key"], "book.pdf#p2-ocr1")

    def test_composite_categories(self):
        self.assertEqual(classify_categories("已知集合A，椭圆E，研究向量的数量积"), ["集合与逻辑用语", "平面向量", "解析几何"])

    def test_cli_file_import_keeps_original_copy(self):
        from scripts.import_question_pool import main
        from hashlib import sha256
        source_file = self.write("book.txt", "1. 集合A有几个元素？【答案】2")
        retained = self.root / "retained"
        captured = []
        def import_mock(source, records):
            captured.append(source)
            list(records)
            return {"source_id": 1}
        argv = ["import_question_pool.py", "--source-name", "我的教辅", "--kind", "txt", "--path", str(source_file)]
        with patch("sys.argv", argv), patch("backend.question_pool.files_directory", return_value=retained), patch("backend.question_pool.import_records", side_effect=import_mock), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        source = captured[0]
        self.assertEqual(source["filename"], "book.txt")
        self.assertEqual(source["file_token"], sha256(source_file.read_bytes()).hexdigest() + ".txt")
        self.assertEqual((retained / source["file_token"]).read_bytes(), source_file.read_bytes())


if __name__ == "__main__":
    unittest.main()
