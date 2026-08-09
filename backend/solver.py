"""
做题系统：三阶流程（最终版）
Solver（1 次调用）：解答并输出板块
  └─ 雪碧了检测
Verifier（1 次调用）：切大块/小块 + 归类知识点 + 打分
Formatter（1 次调用）：全局校验 + 聚合入库
"""

import os
import json
import re, sys
import httpx
from typing import Dict, Any, List, Optional

from backend import difficulty as diff
import backend.settings as runtime_settings
from backend.categories import CATEGORIES

# ---------- 目录 ----------
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# ---------- 正则 ----------
SOLVER_STATUS_PATTERN = re.compile(r'^\[(?:状态|确认|修正)：(.+?)\]')
BRIEF_PATTERN = re.compile(r'^简略过程[：:]\s*(.*)$')
STANDARD_PATTERN = re.compile(r'^标准过程[：:]\s*(.*)$')
DETAIL_PATTERN = re.compile(r'^详细过程[：:]\s*(.*)$')
KNOWLEDGE_POINT_PATTERN = re.compile(r'^知识点[：:]\s*(.+)$')
STEP_HEADER_PATTERN = re.compile(r'^(?:#{1,6}\s*|\*\*\s*)?步骤\s*([一二三四五六七八九十]+|\d+)\s*(?:[（(]?小块[）)]?)?[：:]\s*(.*?)\s*\**$')
OPTION_STEP_PATTERN = re.compile(r'^(?:#{1,6}\s*|\*\*\s*)([A-H])\s*(?:选项|、|\.|．)?\s*(?:[:：]\s*(.*?))?\s*\**$')
CN_STEP_HEADER_PATTERN = re.compile(r'^(?:#{1,6}\s*|\*\*\s*)?第\s*([一二三四五六七八九十]+|\d+)\s*步\s*[：:]\s*(.*?)\s*\**$')
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
FINAL_ANSWER_LINE_PATTERN = re.compile(r'^(?:最终答案|正确答案|答案)\s*[：:]\s*(.+)$')
TOTAL_DIFF_PATTERN = re.compile(r'总分\s*[：:]\s*\$?(\d+)\$?\s*分?\s*[→\-]?\s*(容易|中等|困难|极难)')
KP_LINE_PATTERN = re.compile(r'^(?:块知识点|知识点)\s*[：:]\s*(.+)$')
CHUNK_PATTERN = re.compile(r'###\s*块(\d+)\s*')

# Verifier 输出中的块级字段
BLOCK_TYPE_PATTERN = re.compile(r'^块类型[：:]\s*(.+)$')
BLOCK_CATEGORY_PATTERN = re.compile(r'^板块[：:]\s*(.+)$')
# Solver 输出中的校验模板字段
VERIFIER_TEMPLATE_PATTERN = re.compile(r'^所需校验模板[：:]\s*(.+)$')

# Solver 结构化状态字段
IS_MATH_PATTERN = re.compile(r'^是否数学题[：:]\s*(.+)$')
IS_MISTAKE_PATTERN = re.compile(r'^是否错题[：:]\s*(.+)$')
CAN_SOLVE_PATTERN = re.compile(r'^是否能做出来[：:]\s*(.+)$')
STATUS_PLAIN_PATTERN = re.compile(r'^状态[：:]\s*(.+)$')
BLOCK_DIFFICULTY_PATTERN = re.compile(r'^块难度[：:]\s*(.+)$')
BLOCK_FINAL_ANSWER_PATTERN = re.compile(r'^块最终答案[：:]\s*(.+)$')
BLOCK_KP_PATTERN = re.compile(r'^块知识点[：:]\s*(.+)$')
STEP_DIFFICULTY_PATTERN = re.compile(r'^步骤难度[：:]\s*(.+)$')
STEP_LEVEL1_PATTERN = re.compile(r'^二级步骤[：:]\s*(.+)$')
DIFF_TABLE_HEADER_PATTERN = re.compile(r'^#{1,6}\s*难度评分')
DIFF_TABLE_ROW_PATTERN = re.compile(r'^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|')
STEP_DIFF_JSON_PATTERN = re.compile(r'^步骤难度\s*[：:]\s*(\{.*\})$')
STEP_DIFF_HEAD_PATTERN = re.compile(r'^步骤难度\s*[：:]\s*$')
STEP_DIFF_LEVEL_PATTERN = re.compile(r'^level\s*[：:]\s*(.+)$')
STEP_DIFF_SCORE_PATTERN = re.compile(r'^score\s*[：:]\s*(\d+)$')
STEP_KP_PATTERN = re.compile(r'^知识点\s*[：:]\s*(.*)$')
CHUNK_META_LINE_PATTERN = re.compile(r'^(块类型|板块|块难度|块最终答案|块知识点)\s*[：:]\s*')
DIMENSION_ALIASES = dict(diff.DIM_ALIASES)


def _strip_bullet(text: str) -> str:
    """去掉步骤/块元数据行常见的 '- '、'* ' 等列表前缀"""
    return re.sub(r'^\s*[-*•]\s*', '', text.strip())


# ---------- 读取 prompt ----------
def _read_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, f"{name}.md"), encoding="utf-8") as f:
        return f.read().strip()

_LATEX_RULES = _read_prompt("latex_rules")


TEACHER_CONFIG = {
    "liangliang": {
        "solver": {"model": "deepseek-v4-flash", "reasoning_effort": None},
        "verifier": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
        "formatter": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
        "grade": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
    },
    "taotao": {
        "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "low"},
        "verifier": {"model": "deepseek-v4-flash", "reasoning_effort": "medium"},
        "formatter": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
        "grade": {"model": "deepseek-v4-flash", "reasoning_effort": "medium"},
    },
    "xuefeng": {
        "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
        "verifier": {"model": "deepseek-v4-flash", "reasoning_effort": "medium"},
        "formatter": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
        "grade": {"model": "deepseek-v4-flash", "reasoning_effort": "medium"},
    },
    "ji": {
        "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
        "verifier": {"model": "deepseek-v4-flash", "reasoning_effort": "high"},
        "formatter": {"model": "deepseek-v4-flash", "reasoning_effort": "high"},
        "grade": {"model": "deepseek-v4-flash", "reasoning_effort": "high"},
    },
}

SOLVER_PROMPT = _read_prompt("solver")
FORMATTER_PROMPT = _read_prompt("formatter")

_VERIFIER_OUTPUT_TEMPLATE = """## 输出格式（必须严格遵守，否则无法入库）

第一行必须输出状态：[确认：可解] / [确认：不会做] / [确认：错题]

如果状态为 [确认：可解]，必须按下面的固定结构输出，不要使用其它格式：

### 块1
块类型：选择题/填空题/多选题/子问/大题
板块：<一级板块名>
块最终答案：<该块的最终答案，多选题直接写 选 AB>
块知识点：<知识点1>、<知识点2>

步骤1：<步骤名>
二级步骤：<二级步骤名，没有就写 null>
标准过程：<标准/简略过程>
详细过程：<详细过程>
知识点：<知识点1>、<知识点2>

步骤2：<步骤名>
...（每个步骤都按同样结构）

格式要求：
1. 块与块之间用 `### 块N` 分隔，步骤与步骤之间用 `---` 分隔。
2. `知识点：` 只能放在各自字段里，不得写进标准过程或详细过程。
3. 不要修改或删除任何推导步骤；步骤名、标准过程、详细过程都必须完整。
4. 多选题的原题开头必须带（多选），块最终答案直接写 `选 AB` 这种紧凑格式。"""


# ---------- API Key ----------
def get_api_key() -> str:
    key = runtime_settings.get_api_key("deepseek")
    if not key:
        raise ValueError("未找到 DEEPSEEK_API_KEY，请在系统设置页配置")
    return key


# ---------- 调用 DeepSeek ----------
def call_deepseek(system_prompt: str, user_prompt: str, temperature: float = 0.3, model: str = "deepseek-chat", reasoning_effort: str = None):
    api_key = get_api_key()
    api_cfg = runtime_settings.get_api().get("deepseek") or {}
    limits = runtime_settings.get_limits()
    timeout_seconds = limits.get("api_timeout_seconds", 300)
    base_url = (api_cfg.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    # 自动注入全局 LaTeX 格式要求
    full_system = system_prompt + "\n\n" + _LATEX_RULES if _LATEX_RULES else system_prompt
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": full_system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": limits.get("api_max_tokens", 32000),
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
        body["thinking"] = {"type": "enabled"}
    try:
        resp = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout_seconds,
        )
        if resp.status_code != 200:
            raise Exception(f"状态码 {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        raise Exception(f"API 请求超时（{timeout_seconds}s）")
    except httpx.ConnectError:
        raise Exception("无法连接到 API 服务器")
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
        raise Exception(f"API 请求异常: {str(e)[:200]}")
    usage = data.get("usage", {})
    return content, usage


# ---------- 提取器 ----------
def _extract_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    first = text.find("{")
    if first >= 0:
        text = text[first:]
    last = text.rfind("}")
    if last >= 0:
        text = text[: last + 1]
    return text.strip()


def _extract_solver_status(text: str) -> Optional[str]:
    """检查 Solver 输出中是否有不会做/错题的标记"""
    for line in text.split("\n"):
        stripped = line.strip()
        m = SOLVER_STATUS_PATTERN.match(stripped)
        if m:
            status = m.group(1).strip()
            if status in ("不会做", "错题"):
                return status
    return None


def _check_solver_viable(content: str) -> Optional[str]:
    """检查 Solver 输出是否可解。返回 None 表示可解，str 表示雪碧了的原因。"""
    def _strip_brackets(s: str) -> str:
        return s.strip().strip('[]')
    for line in content.split("\n"):
        stripped = line.strip()
        m = IS_MATH_PATTERN.match(stripped)
        if m and _strip_brackets(m.group(1)) == "否":
            return "不是数学题"
        m = IS_MISTAKE_PATTERN.match(stripped)
        if m and _strip_brackets(m.group(1)) == "是":
            return "题目本身有错"
        m = CAN_SOLVE_PATTERN.match(stripped)
        if m and _strip_brackets(m.group(1)) == "否":
            return "Solver 判定：不会做"
        m = STATUS_PLAIN_PATTERN.match(stripped)
        if m:
            s = _strip_brackets(m.group(1))
            if s == "不会做":
                return "Solver 判定：不会做"
            if s == "错题":
                return "Solver 判定：错题"
            if s == "非数学题":
                return "不是数学题"
        m = SOLVER_STATUS_PATTERN.match(stripped)
        if m:
            s = m.group(1).strip()
            if s in ("不会做", "错题"):
                return f"Solver 判定：{s}"
    return None


def _extract_category(text: str) -> Optional[str]:
    """从 Solver 输出中提取板块（去掉括号内的子分类再匹配）"""
    for line in text.split("\n"):
        stripped = line.strip()
        m = BLOCK_CATEGORY_PATTERN.match(stripped)
        if m:
            val = m.group(1).strip()
            val = val.strip('[]')
            base = re.sub(r'\s*[（(][^）)]*[）)]\s*$', '', val).strip()
            if base in CATEGORIES:
                return base
            if val in CATEGORIES:
                return val
    return None


def _extract_verifier_template(text: str) -> Optional[str]:
    """从 Solver 输出中提取所需校验模板名"""
    for line in text.split("\n"):
        stripped = line.strip()
        m = VERIFIER_TEMPLATE_PATTERN.match(stripped)
        if m:
            val = m.group(1).strip()
            if val:
                return val
    return None


def _resolve_question_type(question: str, content: str, question_type: str = None) -> str:
    """在 Verifier 前确定题型：优先显式指定，其次题干/ Solver 输出。"""
    if question_type in ("选择题", "填空题", "多选题"):
        return question_type
    if "多选" in (question or ""):
        return "多选题"
    for line in (content or "").split("\n"):
        m = re.match(r"^题型\s*[：:]\s*(.+)$", line.strip())
        if m:
            t = m.group(1).strip().strip("[]")
            if t in ("选择题", "填空题", "多选题"):
                return t
    return question_type or ""


def _parse_chunk_meta(text: str) -> dict:
    """从 Verifier 输出的块内容中提取块级元数据"""
    meta = {"chunk_type": None, "category": None,
            "difficulty": None, "final_answer": "", "knowledge_points": []}
    diff_rows = {}
    in_diff_table = False
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        body = _strip_bullet(stripped)
        if DIFF_TABLE_HEADER_PATTERN.match(body):
            in_diff_table = True
            continue
        if in_diff_table:
            m = DIFF_TABLE_ROW_PATTERN.match(body)
            if m:
                key = m.group(1).strip()
                value = int(m.group(2))
                diff_rows[DIMENSION_ALIASES.get(key, key)] = value
            continue
        m = BLOCK_TYPE_PATTERN.match(body)
        if m:
            meta["chunk_type"] = m.group(1).strip()
            continue
        m = BLOCK_CATEGORY_PATTERN.match(body)
        if m:
            meta["category"] = m.group(1).strip()
            continue
        m = BLOCK_DIFFICULTY_PATTERN.match(body)
        if m:
            try:
                parsed_diff = json.loads(m.group(1).strip())
                if isinstance(parsed_diff, dict):
                    dims = parsed_diff.get("dimensions") or {}
                    if isinstance(dims, dict):
                        parsed_diff["dimensions"] = {
                            DIMENSION_ALIASES.get(k, k): v for k, v in dims.items()
                        }
                meta["difficulty"] = parsed_diff
            except (json.JSONDecodeError, ValueError):
                pass
            continue
        m = BLOCK_FINAL_ANSWER_PATTERN.match(body)
        if m:
            meta["final_answer"] = m.group(1).strip()
            continue
        m = FINAL_ANSWER_LINE_PATTERN.match(body)
        if m and not meta["final_answer"]:
            meta["final_answer"] = m.group(1).strip()
            continue
        m = BLOCK_KP_PATTERN.match(body)
        if m:
            kps = [kp.strip().strip("[]") for kp in m.group(1).split("、") if kp.strip()]
            meta["knowledge_points"] = kps
            continue
        m = TOTAL_DIFF_PATTERN.search(body)
        if m and meta["difficulty"] is None:
            meta["difficulty"] = {"level": m.group(2), "total_score": int(m.group(1)), "dimensions": {}}
            continue
        m = KP_LINE_PATTERN.match(body)
        if m:
            kps = [kp.strip().strip("[]") for kp in m.group(1).split("、") if kp.strip()]
            for kp in kps:
                if kp and kp not in meta["knowledge_points"]:
                    meta["knowledge_points"].append(kp)
            continue
    if diff_rows:
        if isinstance(meta["difficulty"], dict):
            dims = dict(meta["difficulty"].get("dimensions") or {})
            dims.update(diff_rows)
            meta["difficulty"]["dimensions"] = dims
        else:
            meta["difficulty"] = {"level": "未知", "total_score": 0, "dimensions": diff_rows}
    return meta


def _parse_steps(text: str, allow_option_steps: bool = True) -> list:
    """从 Verifier 输出中解析步骤（小块）"""
    steps = []
    current_step = None
    in_step = False
    parsing_standard = False
    parsing_detailed = False
    diff_state = 0
    kp_bullet_state = False
    skip_rest = False
    for line in text.split("\n"):
        stripped = line.strip()
        m = STEP_HEADER_PATTERN.match(stripped)
        if not m and allow_option_steps:
            m = OPTION_STEP_PATTERN.match(stripped)
        if not m:
            m = CN_STEP_HEADER_PATTERN.match(stripped)
        if m:
            if current_step is not None:
                current_step.pop("_diff_level", None)
                steps.append(current_step)
            num_raw = m.group(1)
            title_raw = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
            parsing_standard = True
            parsing_detailed = False
            diff_state = 0
            kp_bullet_state = False
            skip_rest = False
            if num_raw.isdigit():
                step_number = int(num_raw)
            elif num_raw in _CN_NUM:
                step_number = _CN_NUM[num_raw]
            else:
                step_number = len(steps) + 1
            current_step = {
                "step_number": step_number,
                "title": (title_raw or ("选项 " + num_raw if not num_raw.isdigit() else "")).strip(),
                "step_level1": None,
                "standard_writing": "",
                "detailed_writing": "",
                "knowledge_point": "",
                "step_difficulty": None,
            }
            in_step = True
            continue
        if not in_step or current_step is None:
            continue
        if re.match(r'^-{2,}\s*$', stripped) or re.match(r'^\*{2,}\s*$', stripped):
            continue
        body = _strip_bullet(stripped)
        if DIFF_TABLE_HEADER_PATTERN.match(body):
            skip_rest = True
            parsing_standard = False
            parsing_detailed = False
            diff_state = 0
            kp_bullet_state = False
            continue
        if skip_rest:
            continue
        m = STEP_DIFF_JSON_PATTERN.match(body)
        if m:
            try:
                current_step["step_difficulty"] = json.loads(m.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                current_step["step_difficulty"] = {"level": "未知", "score": 0}
            parsing_standard = False
            parsing_detailed = False
            diff_state = 0
            kp_bullet_state = False
            continue
        m = STEP_DIFF_HEAD_PATTERN.match(body)
        if m:
            diff_state = 1
            parsing_standard = False
            parsing_detailed = False
            continue
        if diff_state == 1:
            m = STEP_DIFF_LEVEL_PATTERN.match(body)
            if m:
                current_step["_diff_level"] = m.group(1).strip()
                diff_state = 2
                continue
        if diff_state == 2:
            m = STEP_DIFF_SCORE_PATTERN.match(body)
            if m:
                current_step["step_difficulty"] = {
                    "level": current_step.get("_diff_level") or "未知",
                    "score": int(m.group(1)),
                }
                current_step.pop("_diff_level", None)
                diff_state = 0
                continue
        if diff_state:
            diff_state = 0
        m = STEP_KP_PATTERN.match(body)
        if m:
            parsing_standard = False
            parsing_detailed = False
            kp_raw = m.group(1).strip()
            if kp_raw:
                current_step["knowledge_point"] = re.sub(r'^\[(.+)\]$', r'\1', kp_raw)
                kp_bullet_state = False
            else:
                kp_bullet_state = True
            continue
        if kp_bullet_state:
            kp = re.sub(r'^\[(.+)\]$', r'\1', body)
            if kp and kp not in current_step["knowledge_point"]:
                current_step["knowledge_point"] = (current_step["knowledge_point"] + "、" + kp).strip("、")
            continue
        slm = STEP_LEVEL1_PATTERN.match(body)
        if slm:
            parsing_standard = False
            parsing_detailed = False
            current_step["step_level1"] = slm.group(1).strip()
            continue
        bm = BRIEF_PATTERN.match(stripped)
        if not bm:
            bm = BRIEF_PATTERN.match(body)
        if bm:
            current_step["standard_writing"] = bm.group(1).strip()
            parsing_standard = True
            parsing_detailed = False
            continue
        sm = STANDARD_PATTERN.match(stripped)
        if not sm:
            sm = STANDARD_PATTERN.match(body)
        if sm:
            current_step["standard_writing"] = sm.group(1).strip()
            parsing_standard = True
            parsing_detailed = False
            continue
        dm2 = DETAIL_PATTERN.match(stripped)
        if not dm2:
            dm2 = DETAIL_PATTERN.match(body)
        if dm2:
            parsing_standard = False
            parsing_detailed = True
            current_step["detailed_writing"] = dm2.group(1).strip()
            continue
        if CHUNK_META_LINE_PATTERN.match(body):
            parsing_standard = False
            parsing_detailed = False
            continue
        if parsing_standard:
            if current_step["standard_writing"]:
                current_step["standard_writing"] += "\n" + stripped
            else:
                current_step["standard_writing"] = stripped
            continue
        if parsing_detailed:
            if current_step["detailed_writing"]:
                current_step["detailed_writing"] += "\n" + stripped
            else:
                current_step["detailed_writing"] = stripped
            continue
        if current_step and current_step["detailed_writing"]:
            current_step["detailed_writing"] += "\n" + stripped
            continue
    if current_step is not None:
        current_step.pop("_diff_level", None)
        steps.append(current_step)
    return steps


# ---------- 按 ### 块N 拆分 ----------
def _split_chunks(text: str) -> tuple:
    """按 ### 块N 分割文本，返回 (header, chunks)"""
    parts = CHUNK_PATTERN.split(text)
    if len(parts) < 3:
        return text.strip(), [{"id": 1, "content": text}]
    header = parts[0].strip()
    chunks = []
    for i in range(1, len(parts) - 1, 2):
        chunk_id = int(parts[i])
        content = parts[i + 1].strip()
        chunks.append({"id": chunk_id, "content": content})
    return header, chunks


# ---------- Verifier 路由 ----------
# 映射：categories.py 的板块名 → prompt 文件名（与 steps.yaml 题型名一致）
_CATEGORY_TO_PROMPT_FILE = {
    # 有大题对应 prompt 的板块
    "函数与导数": "函数与导数大题",
    "三角函数": "解三角形大题",
    "概率统计": "简单的概率统计大题",
    "立体几何": "立体几何大题",
    "解析几何": "解析几何大题",
    "数列": "数列大题",
}


def _make_kp_list() -> str:
    """生成所有三级知识点的平铺列表"""
    import yaml
    kp_path = os.path.join(os.path.dirname(__file__), "categories.yaml")
    try:
        with open(kp_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except:
        return ""
    all_l3 = []
    for l1, l2_dict in data.items():
        for l2_name, l3_list in l2_dict.items():
            all_l3.extend(l3_list)
    lines = []
    group = []
    for item in all_l3:
        group.append(item)
        if len(group) >= 6:
            lines.append("\u3001".join(group))
            group = []
    if group:
        lines.append("\u3001".join(group))
    kp_text = "\n".join(lines)
    return (
        "\n\n## \u77e5\u8bc6\u70b9\u5206\u7c7b\n\n"
        "\u77e5\u8bc6\u70b9 **\u53ea\u80fd** \u4ece\u4ee5\u4e0b\u5217\u8868\u4e2d\u9009\u53d6\uff0c\u4e0d\u8981\u81ea\u5df1\u521b\u9020\uff1a\n\n"
        + kp_text
        + "\n\n\u6bcf\u4e2a\u6b65\u9aa4\u6807\u6ce8 **1-3 \u4e2a** \u6700\u76f8\u5173\u7684\u77e5\u8bc6\u70b9\u5373\u53ef\u3002"
    )



def _load_verifier_prompt(category: str) -> str:
    """加载对应板块的 Verifier prompt，动态追加三级知识点列表"""
    file_name = _CATEGORY_TO_PROMPT_FILE.get(category, category)
    path = os.path.join(PROMPTS_DIR, "verifiers", f"{file_name}.md")
    if not os.path.exists(path):
        fallback = os.path.join(PROMPTS_DIR, "verifiers", "简单的非标准题目.md")
        if os.path.exists(fallback):
            with open(fallback, encoding="utf-8") as f:
                return f.read().strip() + "\n\n" + _make_kp_list()
        raise FileNotFoundError(f"找不到板块对应的 verifier: {category}")
    with open(path, encoding="utf-8") as f:
        prompt = f.read().strip()
    # 去掉硬编码的旧知识点段落
    while "## 知识点分类" in prompt:
        idx = prompt.find("## 知识点分类")
        rest = prompt[idx + len("## 知识点分类"):]
        next_sec = rest.find("\n## ")
        if next_sec >= 0:
            prompt = prompt[:idx] + rest[next_sec:]
        else:
            prompt = prompt[:idx].rstrip()
    prompt += "\n\n" + _make_kp_list()
    if "## 输出格式（必须严格遵守" not in prompt:
        prompt += "\n\n" + _VERIFIER_OUTPUT_TEMPLATE
    return prompt


def _extract_verifier_status(text: str) -> Optional[str]:
    """提取 Verifier 输出第一行的状态标记"""
    first_line = text.strip().split("\n")[0].strip()
    m = SOLVER_STATUS_PATTERN.match(first_line)
    if m:
        return m.group(1).strip()
    return None


def _xuebile(status: str, detail: str = "") -> dict:
    return {
        "error": "雪碧了",
        "status": status,
        "detail": detail or f"Solver 标记为：{status}",
        "steps": [],
        "final_answer": f"无法解答（{status}）",
        "chunk_results": [],
    }


# ---------- Solver 步 ----------
def step_solver_only(question: str, question_type: str = None, teacher: str = None) -> dict:
    """Solver：解答 + 输出板块"""
    config = runtime_settings.get_teacher_config(teacher)
    prompt = SOLVER_PROMPT
    if question_type:
        prompt += f"\n\n注意：已知本题为{question_type}。"
    solver_cfg = config["solver"]
    content, usage = call_deepseek(prompt, question, model=solver_cfg["model"], reasoning_effort=solver_cfg.get("reasoning_effort"))
    viable_reason = _check_solver_viable(content)
    if viable_reason:
        return _xuebile("不可解", viable_reason)
    cat = _extract_category(content)
    return {
        "content": content,
        "category": cat or question_type,
        # 向后兼容：前端 Step1 期望 chunks
        "chunks": [{"id": 1, "type": question_type or "整体", "content": content, "category": cat}],
        "token_usage": usage,
    }


# ---------- Verifier 步（一次调用，切全部）----------

def _validate_step_names(verifier_cat: str, steps: list) -> list:
    """验证步骤名是否来自 steps.yaml 的预定义列表。
       新版 Verifier prompt 格式：
         步骤N：<一级步骤名>    → title = 一级步骤名（对应 steps.yaml keys）
         二级步骤：<二级步骤名> → step_level1 = 二级步骤名（对应 steps.yaml values，带括号后缀）
       非法步骤名将被重置并记录警告。"""
    try:
        from backend.steps import get_all_level1_names, get_all_level2_names
    except ImportError:
        return steps
    prompt_file = _CATEGORY_TO_PROMPT_FILE.get(verifier_cat) or verifier_cat
    valid_l1 = set(get_all_level1_names(prompt_file))  # steps.yaml keys = 一级步骤名
    valid_l2 = set(get_all_level2_names(prompt_file))  # steps.yaml values = 具体步骤名（无括号后缀）
    if not valid_l1 and not valid_l2:
        return steps
    for step in steps:
        title = step.get("title", "")
        step_level1 = step.get("step_level1")
        # title（一级步骤名）校验：对 steps.yaml keys
        if title and valid_l1 and title not in valid_l1:
            print(f"[Warn] 步骤 {step.get('step_number')}: 一级步骤名 '{title}' 不在预定义列表中，已重置", file=sys.stderr)
            step["title"] = ""
        # step_level1（二级步骤名）校验：去掉括号后缀后对 steps.yaml values
        if step_level1 and valid_l2:
            cleaned = re.sub(r'\s*[（(][^）)]*[）)]\s*$', '', step_level1).strip()
            if cleaned not in valid_l2:
                print(f"[Warn] 步骤 {step.get('step_number')}: 二级步骤名 '{step_level1}'（清理后 '{cleaned}'）不在预定义列表中，已重置", file=sys.stderr)
                step["step_level1"] = None
    return steps


def step_verify_all(content: str, question: str, category: str = None, question_type: str = None, teacher: str = None) -> dict:
    """一次 Verifier：将完整解答切成大块/小块 + 归类知识点 + 打分"""
    config = runtime_settings.get_teacher_config(teacher)
    resolved_type = _resolve_question_type(question, content, question_type)
    if resolved_type in ("选择题", "填空题", "多选题"):
        verifier_cat = resolved_type
    else:
        # 优先使用 Solver 输出的校验模板
        verifier_template = _extract_verifier_template(content)
        if verifier_template:
            verifier_cat = verifier_template
        else:
            verifier_cat = category
            if not verifier_cat:
                verifier_cat = _extract_category(content)
            if not verifier_cat:
                verifier_cat = "函数与导数"  # 最后兜底

    verifier_prompt = _load_verifier_prompt(verifier_cat)
    user_prompt = f"原题：{question}\n\n解答内容：\n{content}"
    v_model = config["verifier"]["model"]
    verified_out, v_usage = call_deepseek(verifier_prompt, user_prompt, temperature=0.3, model=v_model)

    # 解析 Verifier 输出（可能含多个 ### 块N）
    header, raw_chunks = _split_chunks(verified_out)


    chunk_results = []
    for pc in raw_chunks:
        meta = _parse_chunk_meta(pc["content"])
        steps = _parse_steps(pc["content"], allow_option_steps=(verifier_cat == "多选题"))
        if not steps:
            print(f"[Verifier] {verifier_cat} 未解析到步骤，输出片段: {pc['content'][:300]}", file=sys.stderr)
            steps = [{
                "step_number": 1,
                "title": (meta.get("chunk_type") or "解答")[:30],
                "step_level1": None,
                "standard_writing": pc["content"],
                "detailed_writing": pc["content"],
                "knowledge_point": "",
                "step_difficulty": None,
            }]
        for step in steps:
            if not step.get("standard_writing"):
                fallback_text = step.get("detailed_writing") or ""
                if not fallback_text and len(steps) == 1:
                    fallback_text = pc["content"]
                step["standard_writing"] = fallback_text
            # 详细过程缺失时用标准过程兜底，避免 Formatter 判为不完整
            if not step.get("detailed_writing"):
                step["detailed_writing"] = step.get("standard_writing", "")
            if not step.get("title") and step.get("standard_writing"):
                step["title"] = step.get("standard_writing", "")[:30]
        steps = _validate_step_names(verifier_cat, steps)

        seen = set()
        unique_kps = []
        for kp in meta.get("knowledge_points", []):
            if kp not in seen:
                seen.add(kp)
                unique_kps.append(kp)

        chunk_results.append({
            "chunk_id": pc["id"],
            "chunk_type": meta.get("chunk_type") or resolved_type or category or "整体",
            "category": {"level1": meta.get("category") or category or "整体", "level2": None},
            "difficulty": dict(diff.UNKNOWN_DIFFICULTY),
            "steps": steps,
            "final_answer": meta.get("final_answer", ""),
            "knowledge_points": unique_kps,
        })
        for step in steps:
            missing = [k for k in ("title", "standard_writing", "detailed_writing") if not str(step.get(k) or "").strip()]
            if missing:
                print(f"[Verifier] 步骤 {step.get('step_number')} 缺字段 {missing}: {json.dumps(step, ensure_ascii=False)[:300]}", file=sys.stderr)
    # 知识点过滤：只保留 CATEGORIES 中存在的子板块名
    _all_valid_kps = set()
    for subs in CATEGORIES.values():
        _all_valid_kps.update(subs)
    for cr in chunk_results:
        cr["knowledge_points"] = [kp for kp in cr.get("knowledge_points", []) if kp in _all_valid_kps]
    overall_diff = dict(diff.UNKNOWN_DIFFICULTY)
    return {"chunk_results": chunk_results, "token_usage": v_usage, "overall_difficulty": overall_diff}


# ---------- 向后兼容：Step2 API ----------
def step_verify_chunk(chunk: dict, question: str, solved: list) -> dict:
    """保留给前端 Step2 API 调用，走新的单次 Verifier"""
    cat = chunk.get("category")
    result = step_verify_all(chunk["content"], question, cat)
    cr = result["chunk_results"]
    return {"result": cr[0] if cr else {}, "token_usage": result["token_usage"]}


# ---------- Formatter：全局校验 ----------
def _is_well_formed_chunk_results(chunk_results) -> bool:
    """Formatter 输出必须保留每个步骤的标题、标准过程和详细过程，否则视为不合格。"""
    if not isinstance(chunk_results, list) or not chunk_results:
        return False
    for cr in chunk_results:
        if not isinstance(cr, dict):
            return False
        steps = cr.get("steps")
        if not isinstance(steps, list) or not steps:
            return False
        for step in steps:
            if not isinstance(step, dict):
                return False
            if not (step.get("title") or "").strip():
                return False
            if not (step.get("standard_writing") or "").strip():
                return False
            if not (step.get("detailed_writing") or "").strip():
                return False
    return True


def _aggregate_from_chunks(question: str, chunk_results: list, token_total: dict) -> dict:
    """聚合 Verifier 输出为最终 JSON（Formatter 两次都失败时的兜底）。"""
    kps = set()
    answers = []
    for cr in chunk_results:
        for kp in cr.get("knowledge_points", []):
            kps.add(kp)
        if cr.get("final_answer"):
            answers.append(cr["final_answer"])
        for step in cr.get("steps", []):
            if isinstance(step, dict) and step.get("knowledge_point"):
                for part in re.split(r"[、,，;；]+", str(step["knowledge_point"])):
                    part = part.strip()
                    if part:
                        kps.add(part)
        cr["difficulty"] = dict(diff.UNKNOWN_DIFFICULTY)
    return {
        "status": "可解",
        "chunk_results": chunk_results,
        "final_answer": " | ".join(answers) if len(answers) > 1 else (answers[0] if answers else ""),
        "knowledge_points": list(kps),
        "overall_difficulty": dict(diff.UNKNOWN_DIFFICULTY),
        "token_usage": {k: token_total.get(k, 0) for k in token_total},
    }


def _collect_kps_from_steps(chunk_results: list) -> list:
    """从步骤级 knowledge_point 去重收集知识点。"""
    out = []
    seen = set()
    for cr in chunk_results or []:
        if not isinstance(cr, dict):
            continue
        for step in cr.get("steps", []) or []:
            if not isinstance(step, dict) or not step.get("knowledge_point"):
                continue
            for part in re.split(r"[、,，;；]+", str(step["knowledge_point"])):
                part = part.strip()
                if part and part not in seen:
                    seen.add(part)
                    out.append(part)
    return out


def _call_formatter(question: str, chunk_results: list, token_total: dict, teacher: str):
    """调用 Formatter 补齐步骤五维，返回 (result, reason)。result 为 None 表示失败。"""
    config = runtime_settings.get_teacher_config(teacher)
    f_cfg = config["formatter"]
    input_data = {
        "question": question,
        "chunk_results": chunk_results,
    }
    formatted, usage = call_deepseek(
        FORMATTER_PROMPT,
        json.dumps(input_data, ensure_ascii=False, indent=2),
        temperature=0.2, model=f_cfg["model"], reasoning_effort=f_cfg.get("reasoning_effort")
    )
    for k in token_total:
        token_total[k] += usage.get(k, 0)
    try:
        result = json.loads(_extract_json(formatted))
    except (json.JSONDecodeError, ValueError):
        return None, "Formatter 输出不是合法 JSON"
    if not isinstance(result, dict):
        return None, "Formatter 输出结构异常"
    if "error" in result:
        return None, str(result.get("reason") or result.get("error") or "Formatter 判定题目有误")
    crs = result.get("chunk_results")
    if not _is_well_formed_chunk_results(crs):
        return None, "Formatter 输出缺少完整步骤"
    if not diff.has_step_dimensions(crs):
        return None, "Formatter 未给每个步骤输出五维难度"
    try:
        _, overall = diff.aggregate_chunk_results(crs)
    except Exception as e:
        return None, f"难度聚合失败: {str(e)[:100]}"
    result["overall_difficulty"] = overall
    result["chunk_results"] = crs
    if not result.get("knowledge_points"):
        result["knowledge_points"] = _collect_kps_from_steps(crs)
    result["token_usage"] = {k: token_total.get(k, 0) for k in token_total}
    return result, None


def step_final_check(question: str, chunk_results: list, chunks_raw: list, token_total: dict, teacher: str = None,
                     solver_content: str = None, verifier_category: str = None, question_type: str = None) -> dict:
    """Formatter 评分 + 聚合；失败时重跑一次 Verifier 再试，仍失败则报错并保留新 Verifier 结果。"""
    result, reason = _call_formatter(question, chunk_results, token_total, teacher)
    if result:
        return result

    retried = None
    if solver_content:
        try:
            retried = step_verify_all(
                solver_content, question, verifier_category,
                question_type=question_type, teacher=teacher,
            )
        except Exception as e:
            print(f"[Formatter] Verifier 重跑失败: {str(e)[:200]}", file=sys.stderr)
            retried = None
        if retried and not retried.get("error"):
            result, reason2 = _call_formatter(question, retried["chunk_results"], token_total, teacher)
            if result:
                return result
            reason = reason2 or reason

    fallback_crs = retried["chunk_results"] if retried else chunk_results
    fallback = _aggregate_from_chunks(question, fallback_crs, token_total)
    fallback["error"] = "formatter_failed"
    fallback["formatter_fallback"] = True
    fallback["formatter_note"] = (
        "Formatter 未通过校验，已保留 Verifier 结果，难度未知，可能有错误。"
        f"原因：{reason}"
    )
    return fallback
