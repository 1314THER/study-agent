"""Loss-aware source readers for the owner's question pool.

These readers never solve questions or turn inferred conditions into source text.
Every input item has a stable locator, including malformed records and scan pages.
Paid OCR is opt-in through ``options={"ocr": True}`` for explicit file uploads.
"""

import json
import re
import zipfile
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

from backend.categories import CATEGORIES

SOURCE_KINDS = ("compilation", "highmath", "conic10k", "jsonl", "pdf", "docx", "image", "txt")
COMPLETENESS = {"complete", "needs_review", "deferred_graphic", "failed"}

# Strong evidence of information specified only in an unavailable drawing.
_GRAPH_DEPENDENCY = re.compile(
    r"(?:如[下右左]?图|图中|图示|如图所示|根据[下右左]?图|由图可知|从图中|三视图|"
    r"茎叶图|频率分布直方图|程序框图|流程图|下列[四各]?图|阴影部分|阴影区域|"
    r"图\s*[1-9一二三四]\s*(?:所示|给出|中))"
)
_GRAPH_COMMAND = re.compile(
    r"\\(?:bitmapfigure|choicebitmap|includegraphics|tikzfigure|input|include)\b(?:\[[^\]]*\])?\s*\{[^}]*\}"
    r"|\\begin\{(?:tikzpicture|pspicture|picture)\}"
    r"|!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>", re.I
)
_ALLOWED_TYPES = {"选择题", "多选题", "填空题", "大题", "单选题", "解答题"}


def _question_type(item):
    aliases = {"单选题": "选择题", "解答题": "大题", "single_choice": "选择题",
               "multiple_choice": "多选题", "fill_in_blank": "填空题", "solution": "大题"}
    for field in ("question_type", "type", "multiple", "subject"):
        value = item.get(field)
        if isinstance(value, str):
            value = value.strip()
            if value in _ALLOWED_TYPES:
                return aliases.get(value, value)
            if value in aliases:
                return aliases[value]
    return ""


def classify_categories(text: str, hint: str = "") -> list:
    """Suggest broad existing chapters only; ambiguous items remain unclassified."""
    patterns = {
        "集合与逻辑用语": r"集合|全集|子集|交集|并集|补集|命题|充要条件|充分[不]?必要|必要[不]?充分|\\(?:cup|cap|subset|complement)\b",
        "不等式": r"不等式|均值不等|基本不等|线性规划|可行域",
        "一元二次式": r"一元二次|二次方程|二次不等式|二次函数|判别式|韦达",
        "函数与导数": r"函数|导数|导函数|切线斜率|零点|单调|极值|定义域|值域|奇函数|偶函数",
        "指对幂耐克函数": r"指数函数|对数|幂函数|耐克|\\(?:log|ln)\b",
        "三角函数": r"三角函数|解三角形|正弦|余弦|正切|弧度|\\(?:sin|cos|tan|cot|arcsin|arccos)\b",
        "平面向量": r"平面向量|向量|数量积|\\overrightarrow\b",
        "复数": r"复数|复平面|虚部|实部|共轭|虚数|\\(?:mathrm\{i\}|i\b)",
        "立体几何": r"棱柱|棱锥|棱台|圆柱|圆锥|圆台|三视图|正方体|长方体|多面体|二面角|异面|空间向量|球的|球面|直线与平面|平面与平面",
        "数列": r"数列|等差|等比|前\s*[nN]\s*项和|数学归纳",
        "解析几何": r"椭圆|双曲线|抛物线|圆锥曲线|离心率|焦点|圆的方程|圆心|轨迹|直线.*方程|圆\s*\$|圆\\\(",
        "概率统计": r"概率|统计|随机|分布列|方差|标准差|平均数|抽样|回归|相关系数|排列|组合|二项式|计数原理|列联表",
    }
    found = [name for name in CATEGORIES if re.search(patterns[name], text)]
    # A source family is a fallback, never a reason to label all mixed-family items.
    fallback = {
        "Counting_Principle": "概率统计", "Statistics_Probability": "概率统计",
        "Sequence": "数列", "Solid_Geometry": "立体几何",
        "Plane_Analytic_Geometry": "解析几何", "Function_Derivative": "函数与导数",
        "Trigonometric_Functions_and_Triangle_Solving": "三角函数", "conic10k": "解析几何",
    }
    if not found and hint in fallback:
        found = [fallback[hint]]
    return found


def _string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False)


def _record(key, question="", answer="", solution="", **fields):
    record = {
        "source_key": str(key), "question": _string(question), "answer": _string(answer),
        "solution": _string(solution), "categories": [], "question_type": "", "year": None,
        "region": "", "question_no": "", "page_start": None, "page_end": None,
        "completeness": "complete", "reason": "", "raw": {},
    }
    record.update(fields)
    if not record["categories"]:
        record["categories"] = classify_categories(record["question"])
    record["categories"] = list(dict.fromkeys(c for c in record["categories"] if c in CATEGORIES))
    if record["completeness"] not in COMPLETENESS:
        record["completeness"] = "needs_review"
        record["reason"] = "来源的完整性标记未知，请人工核对"
    if record["completeness"] in ("failed", "deferred_graphic"):
        return record
    reasons = [record["reason"]] if record["reason"] else []
    if not record["question"] and record["raw"].get("scan"):
        return record
    if not record["question"]:
        record["completeness"] = "failed"
        reasons.append("题干为空，保留来源原文待修正")
    elif _GRAPH_DEPENDENCY.search(record["question"]) or r"\choicebitmap" in record["question"]:
        record["completeness"] = "deferred_graphic"
        reasons.append("题干引用图形信息，本阶段暂缓，保留出处")
    elif _GRAPH_COMMAND.search(record["question"]):
        record["completeness"] = "needs_review"
        reasons.append("原题含图形标记，请确认文字条件是否完整")
    if record["completeness"] != "failed" and not record["answer"]:
        if record["completeness"] == "complete":
            record["completeness"] = "needs_review"
        reasons.append("来源未提供原答案")
    record["reason"] = "；".join(dict.fromkeys(reasons))
    return record


def _error(key, exc, raw=None, **fields):
    return _record(key, completeness="failed", reason=str(exc)[:1000], raw=raw or {}, **fields)


def _files(path: Path, suffixes):
    if path.is_file():
        yield path
    else:
        yield from sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in suffixes)


def _relative(file: Path, root: Path) -> str:
    return file.relative_to(root).as_posix() if root.is_dir() else file.name


def _json_items(file: Path):
    """Yield line/index plus original record, including parse errors."""
    if file.suffix.lower() == ".jsonl":
        with file.open(encoding="utf-8-sig", errors="replace") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    yield number, json.loads(line), None
                except (ValueError, TypeError) as exc:
                    yield number, {"original_line": line.rstrip("\r\n")}, str(exc)
        return
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError, UnicodeError) as exc:
        yield 1, {"file": file.name}, str(exc)
        return
    if isinstance(data, dict):
        data = data.get("questions", data.get("data", data.get("items", [data])))
    if not isinstance(data, list):
        yield 1, {"original": data}, "JSON 顶层不是题目列表"
        return
    for index, item in enumerate(data, 1):
        yield index, item, None


def _iter_json(root: Path, kind: str):
    for file in _files(root, {".json", ".jsonl"}):
        if file.name.endswith("manifest.json"):
            continue
        rel = _relative(file, root)
        for number, item, error in _json_items(file):
            key = f"{rel}#{number}"
            if error or not isinstance(item, dict):
                yield _error(key, error or "题目记录不是对象", {"item": item, "index": number})
                continue
            if kind == "highmath":
                question = item.get("problem", "")
                solution = item.get("steps", "")
                answer = item.get("answer", "")
                hint = item.get("type", file.stem)
            elif kind == "conic10k":
                question = item.get("text", "")
                solution = item.get("process", "")
                answer = item.get("answer", item.get("answer_expressions", ""))
                hint = "conic10k"
            else:
                question = item.get("question", item.get("content", item.get("latex", item.get("text", item.get("problem", "")))))
                answer = item.get("answer", "")
                solution = item.get("solution", item.get("analysis", item.get("steps", "")))
                hint = ""
            categories = item.get("categories", [])
            if not isinstance(categories, list):
                categories = [categories] if isinstance(categories, str) else []
            categories = [c for c in categories if c in CATEGORIES] or classify_categories(_string(question), hint)
            qtype = _question_type(item)
            yield _record(
                item.get("source_key", key) if kind == "jsonl" else key, question, answer, solution,
                categories=categories, question_type=qtype, year=item.get("year"),
                region=_string(item.get("region", "")), question_no=_string(item.get("question_no", number)),
                page_start=item.get("page_start"), page_end=item.get("page_end"),
                completeness=item.get("completeness", "complete") if kind == "jsonl" else "complete",
                reason=_string(item.get("reason", "")) if kind == "jsonl" else "",
                raw={"file": rel, "index": number, "original": item},
            )


def _balanced(text: str, start: int):
    """Read one TeX braced argument without losing nested fractions."""
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] != "{":
        return None, start
    level = 1
    pos = start + 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
            continue
        if text[pos] == "{":
            level += 1
        elif text[pos] == "}":
            level -= 1
            if not level:
                return text[start + 1:pos], pos + 1
        pos += 1
    return None, start


def _tex_text(text: str) -> str:
    """Convert source layout macros, preserving mathematical LaTeX."""
    text = re.sub(r"(?m)(?<!\\)%.*$", "", text)
    # The UI renders safe text and math, not LaTeX's page-layout environments.
    # Keep tabular data as rows of text while retaining every cell value.
    def table(match):
        body = re.sub(r"\\(?:hline|toprule|midrule|bottomrule)\b|\\cline\s*\{[^}]+\}", "", match[1])
        rows = []
        for row in re.split(r"\\\\(?:\[[^\]]*\])?", body):
            row = row.strip()
            if row:
                rows.append(" | ".join(cell.strip() for cell in re.split(r"(?<!\\)&", row)))
        return "\n" + "\n".join(rows) + "\n"
    text = re.sub(r"\\begin\{tabular\}(?:\[[^\]]*\])?\{[^{}]+\}(.*?)\\end\{tabular\}", table, text, flags=re.S)
    # The source's choices macro takes four braced arguments, often with nested math.
    cursor = 0
    while True:
        match = re.search(r"\\choices\b(?:\[[^\]]*\])?", text[cursor:])
        if not match:
            break
        start = cursor + match.start()
        pos = cursor + match.end()
        values = []
        for _ in range(4):
            value, end = _balanced(text, pos)
            if value is None:
                break
            values.append(value)
            pos = end
        if len(values) == 4:
            replacement = "\n" + "\n\n".join(f"{letter}. {value.strip()}" for letter, value in zip("ABCD", values)) + "\n"
            text = text[:start] + replacement + text[pos:]
            cursor = start + len(replacement)
        else:
            cursor = cursor + match.end()
    # The second slash in \\[4pt] is row spacing, not a display delimiter.
    text = re.sub(r"(?<!\\)\\[()]", "$", text)
    text = re.sub(r"(?<!\\)\\[\[\]]", "$$", text)
    text = re.sub(r"\\(R|N|Z|Q|C)\b", lambda m: r"\mathbb{" + m[1] + "}", text)
    # Braces retain each source macro as one argument in e.g. \frac1\e.
    text = re.sub(r"\\i(?![A-Za-z])", r"{\\mathrm{i}}", text)
    text = re.sub(r"\\e(?![A-Za-z])", r"{\\mathrm{e}}", text)
    text = re.sub(r"\\bs(?![A-Za-z])", r"\\boldsymbol", text)
    # A blank inside math needs a valid math macro; outside math it stays text.
    def blank(match):
        prefix = text[:match.start()]
        inline = (len(re.findall(r"(?<!\\)\$(?!\$)", prefix)) % 2) == 1
        display = prefix.count("$$") % 2 == 1
        return r"\underline{\qquad}" if inline or display else "______"
    text = re.sub(r"\\fillinblank(?:\[[^\]]*\])?\s*\{\s*\}", blank, text)
    text = re.sub(r"\\circled\s*\{([^}]+)\}", r"\\text{(\1)}", text)
    text = re.sub(r"\\(?:smallskip|medskip|bigskip|noindent|clearpage|newpage)\b", "\n", text)
    counters = []
    def list_token(match):
        value = match[0]
        if value.startswith(r"\begin"):
            counters.append(["itemize" if "itemize" in value else "number", 0])
            return "\n"
        if value.startswith(r"\end"):
            if counters:
                counters.pop()
            return "\n"
        if counters:
            counters[-1][1] += 1
            label = "•" if counters[-1][0] == "itemize" else f"({counters[-1][1]})"
        else:
            label = "•"
        optional = re.search(r"\[([^\]]+)\]", value)
        return "\n" + (optional[1] if optional else label) + " "
    text = re.sub(r"\\(?:begin|end)\{(?:enumerate|itemize|circlelist)\}(?:\[[^\]]*\])?|\\item(?:\[[^\]]*\])?[ \t]*", list_token, text)
    text = re.sub(r"\\(?:begin|end)\{(?:center|flushleft|flushright)\}", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _environment(text: str, name: str) -> str:
    match = re.search(r"\\begin\{" + name + r"\}(.*?)\\end\{" + name + r"\}", text, re.S)
    return match[1] if match else ""


def _macro_arguments(text: str, name: str):
    for match in re.finditer(r"\\" + name + r"\b(?:\[[^\]]*\])?", text):
        value, end = _balanced(text, match.end())
        if value is not None:
            yield match.start(), end, value


def _without_answers(text):
    for name in ("answer", "solution"):
        text = re.sub(r"\\begin\{" + name + r"\}.*?\\end\{" + name + r"\}", "", text, flags=re.S)
        for start, end, _ in reversed(list(_macro_arguments(text, name))):
            text = text[:start] + text[end:]
    return text


def _iter_compilation(root: Path):
    files = list(_files(root, {".tex"}))
    # Full repo directories contain layout/figure TeX; only content files are papers.
    if root.is_dir() and (root / "content").is_dir():
        files = list(_files(root / "content", {".tex"}))
    for file in files:
        rel = _relative(file, root)
        try:
            original = file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            yield _error(rel, exc, {"file": rel})
            continue
        text = re.sub(r"(?m)(?<!\\)%.*$", "", original)
        starts = list(re.finditer(r"\\begin\{problem\}(?:\[[^\]]*\])?", text))
        if not starts:
            yield _error(rel, "未找到 problem 环境，保留整份原文", {"file": rel, "source_text": original})
            continue
        chapter = re.search(r"\\chapter(?:\[[^\]]*\])?\{([^}]+)\}", text)
        title = chapter[1] if chapter else file.stem
        year_match = re.search(r"(?:19|20)\d{2}", title + " " + rel)
        year = int(year_match[0]) if year_match else None
        for index, start in enumerate(starts, 1):
            end = starts[index].start() if index < len(starts) else len(text)
            block = text[start.start():end]
            question_end = block.find(r"\end{problem}")
            raw = {"file": rel, "index": index, "paper": title,
                   "line_start": text.count("\n", 0, start.start()) + 1,
                   "source_text": block,
                   "graphic_refs": _GRAPH_COMMAND.findall(block)}
            if question_end < 0:
                yield _error(f"{rel}#{index}", "problem 环境未闭合", raw, year=year, question_no=str(index))
                continue
            stem = _without_answers(text[start.end():start.start() + question_end])
            answer = _environment(block, "answer") or "\n".join(v for _, _, v in _macro_arguments(block, "answer"))
            solution = _environment(block, "solution") or "\n".join(v for _, _, v in _macro_arguments(block, "solution"))
            section_matches = list(re.finditer(r"\\section\*?(?:\[[^\]]*\])?\{([^}]+)\}", text[:start.start()]))
            section = section_matches[-1][1] if section_matches else ""
            qtype = "多选题" if "多选" in section else "选择题" if "选" in section else "填空题" if "填空" in section else "大题" if "解答" in section else ""
            # Solution figures are irrelevant to whether the question is text-complete.
            if _GRAPH_COMMAND.search(solution):
                solution = _GRAPH_COMMAND.sub("[原解析含图，本阶段未导入]", solution)
                solution = re.sub(r"\\solutionfigure\s*\{(\[原解析含图，本阶段未导入\])\}", r"\1", solution)
            region = re.sub(r"(?:19|20)\d{2}年", "", title)
            yield _record(f"{rel}#{index}", _tex_text(stem), _tex_text(answer), _tex_text(solution),
                          question_type=qtype, year=year, region=region, question_no=str(index), raw=raw)


_QUESTION_START = re.compile(r"^\s*(?:第\s*(\d{1,3})\s*题\s*[.、:：]?|(\d{1,3})\s*[.．、]\s*)(.*)$")
_ANSWER_SECTION = re.compile(r"^\s*(?:参考答案|答案与解析|参考答案及解析|答案解析)\s*[:：]?\s*$")
_INLINE_ANSWER = re.compile(r"(?:【答案】|\[答案\]|^答案\s*[:：])", re.M)
_INLINE_SOLUTION = re.compile(r"(?:【(?:解析|分析|详解)】|\[(?:解析|分析|详解)\]|^(?:解析|分析|详解)\s*[:：])", re.M)


def _split_answer(text):
    answer_match = _INLINE_ANSWER.search(text)
    solution_match = _INLINE_SOLUTION.search(text)
    stops = [m.start() for m in (answer_match, solution_match) if m]
    question = text[:min(stops)].strip() if stops else text.strip()
    answer = ""
    solution = ""
    if answer_match:
        stop = solution_match.start() if solution_match and solution_match.start() > answer_match.end() else len(text)
        answer = text[answer_match.end():stop].strip()
    if solution_match:
        solution = text[solution_match.end():].strip()
    return question, answer, solution


def _text_page_records(pages, filename: str, force_review=True):
    """Join numbered questions across pages and attach numbered answer sections.

    Plain text extraction cannot prove mathematical formula fidelity, so PDF/DOCX
    fragments require owner review. Unnumbered text is retained as a fragment.
    """
    questions = []
    answers = {}
    current = None
    answer_mode = False
    intro = []
    intro_start = None

    def finish():
        nonlocal current
        if current:
            if answer_mode:
                answers.setdefault(current["number"], []).append(current)
            else:
                questions.append(current)
            current = None

    for page, text in pages:
        for line in text.splitlines():
            if _ANSWER_SECTION.match(line):
                finish()
                answer_mode = True
                continue
            match = _QUESTION_START.match(line)
            if match:
                finish()
                current = {"number": match[1] or match[2], "start": page, "end": page,
                           "lines": [match[3]], "fragments": [{"page": page, "text": line}]}
            elif current:
                current["end"] = page
                current["lines"].append(line)
                current["fragments"].append({"page": page, "text": line})
            elif line.strip():
                intro_start = intro_start or page
                intro.append({"page": page, "text": line})
    finish()
    if intro:
        text = "\n".join(i["text"] for i in intro)
        yield _record(f"{filename}#fragment-{intro_start}", text, completeness="needs_review",
                      reason="未编号原文片段，保留以防切题遗漏", page_start=intro_start, page_end=intro[-1]["page"],
                      raw={"file": filename, "fragments": intro})
    seen = {}
    for item in questions:
        number = item["number"]
        seen[number] = seen.get(number, 0) + 1
        question, answer, solution = _split_answer("\n".join(item["lines"]))
        matches = answers.pop(number, [])
        if len(matches) == 1:
            _, extra_answer, extra_solution = _split_answer("\n".join(matches[0]["lines"]))
            answer = answer or extra_answer or "\n".join(matches[0]["lines"]).strip()
            solution = solution or extra_solution
        reason = "文件文字提取结果，请核对公式与切题边界" if force_review else ""
        if len(matches) > 1:
            reason += "；答案区存在重号，未自动关联"
        yield _record(f"{filename}#q{number}-p{item['start']}-{seen[number]}", question, answer, solution,
                      question_no=number, page_start=item["start"], page_end=item["end"],
                      completeness="needs_review" if force_review else "complete", reason=reason,
                      raw={"file": filename, "fragments": item["fragments"], "answer_fragments": matches})
    for number, fragments in answers.items():
        for index, item in enumerate(fragments, 1):
            yield _record(f"{filename}#answer-{number}-p{item['start']}-{index}", "\n".join(item["lines"]),
                          completeness="needs_review", reason="未匹配到题干的答案片段", question_no=number,
                          page_start=item["start"], page_end=item["end"], raw={"file": filename, "fragments": item["fragments"]})


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _omml(node):
    """Preserve common Word equation forms without calling a text model."""
    tag = node.tag.split("}")[-1]
    children = list(node)
    if tag == "t":
        return node.text or ""
    if tag.endswith("Pr"):
        return ""
    get = lambda name: "".join(_omml(c) for c in node if c.tag == _M + name)
    if tag == "f":
        return r"\frac{" + get("num") + "}{" + get("den") + "}"
    if tag == "sSup":
        return "{" + get("e") + "}^{" + get("sup") + "}"
    if tag == "sSub":
        return "{" + get("e") + "}_{" + get("sub") + "}"
    if tag == "sSubSup":
        return "{" + get("e") + "}_{" + get("sub") + "}^{" + get("sup") + "}"
    if tag == "rad":
        degree = get("deg")
        return r"\sqrt" + ("[" + degree + "]" if degree else "") + "{" + get("e") + "}"
    return "".join(_omml(c) for c in children)


def _docx_pages(file: Path):
    with zipfile.ZipFile(file) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    page = 1
    text = []
    for paragraph in root.iter(_W + "p"):
        if paragraph.find("./" + _W + "pPr/" + _W + "pageBreakBefore") is not None and text:
            yield page, "\n".join(text)
            page += 1
            text = []
        parts = []
        def walk(node):
            nonlocal page, text, parts
            if node.tag in (_M + "oMath", _M + "oMathPara"):
                parts.append("$" + _omml(node) + "$")
                return
            if node.tag == _W + "t":
                parts.append(node.text or "")
            elif node.tag == _W + "tab":
                parts.append("\t")
            elif node.tag in (_W + "drawing", _W + "pict", _W + "object"):
                parts.append("[原文件含图片或嵌入对象，需核对文字条件]")
            elif node.tag == _W + "br":
                if node.attrib.get(_W + "type") == "page":
                    text.append("".join(parts))
                    yield_pages.append((page, "\n".join(text)))
                    page += 1
                    text = []
                    parts = []
                else:
                    parts.append("\n")
            else:
                for child in node:
                    walk(child)
        yield_pages = []
        walk(paragraph)
        for found in yield_pages:
            yield found
        text.append("".join(parts))
    if text:
        yield page, "\n".join(text)


_OCR_PROMPT = """将本页所有数学题、原答案和原解析忠实转录为 JSON 数组。
每项字段：question（题干与所有选项，用 LaTeX）、answer（原答案，没有则空字符串）、
solution（原解析，没有则空字符串）、question_no（原题号）、continuation（是否为上页续文）、
requires_graphic（是否必须看图才能作答）。只转录原文，不补条件、不解题。
页面若只有续文也必须保留；无法识别的内容用[无法识别]标记，不能省略。
"""


def _ocr_items(base64_image, filename, page):
    from backend.multimodal import _call_deepseek_vision
    raw_response = _call_deepseek_vision(image_base64=base64_image, text=_OCR_PROMPT)
    match = re.search(r"```(?:json)?\s*(.*?)```", raw_response, re.S)
    value = json.loads(match[1] if match else raw_response)
    if not isinstance(value, list) or not value:
        raise ValueError("OCR 未返回题目列表，保留原页待重试")
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            yield _error(f"{filename}#p{page}-ocr{index}", "OCR 题目不是对象", {"response": raw_response}, page_start=page, page_end=page)
            continue
        question = item.get("question", "")
        continuation = item.get("continuation") is True
        yield _record(f"{filename}#p{page}-ocr{index}", question, item.get("answer", ""), item.get("solution", ""),
                      question_no=_string(item.get("question_no", "")), page_start=page, page_end=page,
                      completeness="deferred_graphic" if item.get("requires_graphic") is True else "needs_review",
                      reason="OCR 转录需人工核对" + ("；上页续文，请与相邻页合并" if continuation else ""),
                      raw={"file": filename, "page": page, "ocr": item, "continuation": continuation})


def _read_pdf_records(file: Path, options):
    try:
        import fitz
        document = fitz.open(file)
    except Exception as exc:
        yield _error(f"{file.name}#file", exc, {"file": file.name})
        return
    pending_pages = []
    page_numbers = set(options.get("page_numbers") or [])
    with document:
        for number, page in enumerate(document, 1):
            if page_numbers and number not in page_numbers:
                continue
            text = page.get_text("text", sort=True).strip()
            # Scans may have only an embedded text header or page number.
            scan = not text
            if text and len(text) < 120:
                try:
                    page_area = page.rect.width * page.rect.height
                    scan = any(rect.width * rect.height > page_area * 0.65
                               for image in page.get_images() for rect in page.get_image_rects(image[0]))
                except Exception:
                    # Text stays reviewable when a PDF does not expose image bounds.
                    scan = False
            if text and not scan:
                pending_pages.append((number, text))
                continue
            if pending_pages:
                yield from _text_page_records(pending_pages, file.name)
                pending_pages = []
            if options.get("ocr") is True:
                try:
                    import base64
                    from backend.multimodal import _pdf_render_scale
                    scale = _pdf_render_scale(page, 180)
                    png = page.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")
                    yield from _ocr_items(base64.b64encode(png).decode(), file.name, number)
                except Exception as exc:
                    yield _error(f"{file.name}#p{number}-ocr1", exc, {"file": file.name, "page": number}, page_start=number, page_end=number)
            else:
                yield _record(f"{file.name}#p{number}-ocr1", completeness="needs_review",
                              reason="本页疑似扫描内容，等待显式启用 OCR；原页及已有文字片段已保留", page_start=number, page_end=number,
                              raw={"file": file.name, "page": number, "scan": True, "extracted_fragment": text})
        if pending_pages:
            yield from _text_page_records(pending_pages, file.name)


def _iter_pdf(file: Path, options):
    previous = None
    for item in _read_pdf_records(file, options):
        continuation = item["raw"].get("continuation") is True
        adjacent = previous and previous.get("page_end") and item.get("page_start") == previous["page_end"] + 1
        same_number = previous and (not item["question_no"] or item["question_no"] == previous["question_no"])
        if continuation and adjacent and same_number and previous["completeness"] != "failed":
            previous["question"] = "\n".join(filter(None, [previous["question"], item["question"]]))
            previous["solution"] = "\n".join(filter(None, [previous["solution"], item["solution"]]))
            if item["answer"] and item["answer"] != previous["answer"]:
                previous["answer"] = "\n".join(filter(None, [previous["answer"], item["answer"]]))
            previous["page_end"] = item["page_end"]
            previous["categories"] = list(dict.fromkeys(previous["categories"] + item["categories"]))
            if item["completeness"] == "deferred_graphic":
                previous["completeness"] = "deferred_graphic"
            previous["reason"] += "；已按 OCR 续文标记拼接相邻页，请核对"
            previous["raw"].setdefault("continuation_fragments", []).append({"source_key": item["source_key"], **item["raw"]})
            continue
        if previous is not None:
            yield previous
        previous = item
    if previous is not None:
        yield previous


def iter_source_records(path, kind, options=None) -> Iterator[dict]:
    """Read a public dataset or one uploaded file into source-preserving records."""
    root = Path(path)
    options = options or {}
    if kind not in SOURCE_KINDS:
        raise ValueError("不支持的题源类型：" + str(kind))
    if not root.exists():
        raise ValueError("题源文件不存在")
    if kind == "compilation":
        yield from _iter_compilation(root)
    elif kind in ("jsonl", "highmath", "conic10k"):
        yield from _iter_json(root, kind)
    elif kind == "pdf":
        yield from _iter_pdf(root, options)
    elif kind == "docx":
        try:
            yield from _text_page_records(_docx_pages(root), root.name)
        except Exception as exc:
            yield _error(root.name, exc, {"file": root.name})
    elif kind == "txt":
        try:
            text = root.read_text(encoding="utf-8-sig")
            pages = [(number, value) for number, value in enumerate(text.split("\f"), 1)]
            yield from _text_page_records(pages, root.name, force_review=True)
        except Exception as exc:
            yield _error(root.name, exc, {"file": root.name})
    elif kind == "image":
        if options.get("ocr") is True:
            try:
                from backend.multimodal import image_to_base64
                yield from _ocr_items(image_to_base64(str(root)), root.name, 1)
            except Exception as exc:
                yield _error(root.name + "#p1-ocr1", exc, {"file": root.name}, page_start=1, page_end=1)
        else:
            yield _record(root.name + "#p1-ocr1", completeness="needs_review", reason="图片等待显式启用 OCR；原文件已保留",
                          page_start=1, page_end=1, raw={"file": root.name, "scan": True})
