"""统一难度标准：五维是唯一难度来源，后端确定性聚合。

口径：
- 每个步骤由 Formatter 输出五维（0-3 整数）：
  非常规程度 / 计算量 / 分类讨论 / 知识广度 / 条件转化难度
- 块/整题五维 = 对步骤五维逐维做“峰值 + 0.5×非零均值×覆盖率（向下取整）”聚合（0-3）
- 总分 = 五维加权累加（默认：0 不计分，1 记 1 分，2 记 2 分，3 记 4 分，封顶 15），权重/封顶/等级可在设置页调整
- 等级：0-3 容易 | 4-6 中等 | 7-9 困难 | >=10 极难
"""

import backend.settings as runtime_settings

DIM_KEYS = ["非常规程度", "计算量", "分类讨论", "知识广度", "条件转化难度"]
DIM_ALIASES = {
    "常规程度": "非常规程度",
    "理解难度": "条件转化难度",
    "知识点密度": "知识广度",
    "涉及到的知识点数量": "知识广度",
    "知识点数量": "知识广度",
}

# 各分值对总分的权重：1 分只记很少的分，2/3 分权重更大，2/3 越多总分越高
SCORE_WEIGHTS = {0: 0, 1: 1, 2: 2, 3: 4}
SCORE_CAP = 15

LEVEL_THRESHOLDS = [
    (3, "容易"),
    (6, "中等"),
    (9, "困难"),
]

UNKNOWN_DIFFICULTY = {"level": "未知", "total_score": 0, "dimensions": {}}


def _scoring():
    """运行时评分配置：设置文件优先，代码常量兜底。"""
    cfg = runtime_settings.get_scoring()
    weights = cfg.get("weights") or SCORE_WEIGHTS
    cap = cfg.get("cap") or SCORE_CAP
    thresholds = cfg.get("thresholds") or LEVEL_THRESHOLDS
    return weights, cap, thresholds


def _weight_for(weights, value: int) -> int:
    if isinstance(weights, dict):
        return int(weights.get(str(value), weights.get(value, 0)) or 0)
    if isinstance(weights, (list, tuple)) and 0 <= value < len(weights):
        return int(weights[value] or 0)
    return 0


def normalize_dims(dims) -> dict:
    """把任意维度名/取值统一成新五维的 0-3 整数。"""
    if not isinstance(dims, dict):
        return {}
    out = {}
    for k, v in dims.items():
        key = DIM_ALIASES.get(k, k)
        if key not in DIM_KEYS:
            continue
        try:
            num = int(round(float(v)))
        except (TypeError, ValueError):
            continue
        out[key] = max(0, min(3, num))
    return out


def has_step_dimensions(chunk_results) -> bool:
    """每个步骤都必须有 Formatter 给的五维，否则视为评分失败。"""
    for cr in chunk_results or []:
        if not isinstance(cr, dict):
            continue
        for step in cr.get("steps") or []:
            sd = step.get("step_difficulty") or {}
            if not isinstance(sd, dict):
                return False
            if not normalize_dims(sd.get("dimensions")):
                return False
    return bool(chunk_results)


def aggregate_dims(step_vectors: list) -> dict:
    """步骤五维 -> 块/整题五维：峰值 + 0.5×非零均值×覆盖率（向下取整），封顶 3。

    覆盖率项只做轻微升级：重复出现 1 分不会抬分，重复出现 2 分才可能升到 3。
    """
    n = len(step_vectors)
    result = {}
    for key in DIM_KEYS:
        nonzero = []
        for vec in step_vectors:
            v = vec.get(key, 0) if isinstance(vec, dict) else 0
            if isinstance(v, (int, float)) and v > 0:
                nonzero.append(float(v))
        if not nonzero:
            result[key] = 0
            continue
        peak = max(nonzero)
        mean = sum(nonzero) / len(nonzero)
        coverage = len(nonzero) / n if n else 0.0
        result[key] = min(3, peak + int(0.5 * mean * coverage))
    return result


def score_from_dims(dims) -> int:
    """五维 -> 0-cap：按设置里的权重加权累加（默认 0/1/2/4），封顶 cap。"""
    normalized = normalize_dims(dims)
    if not normalized:
        return 0
    weights, cap, _ = _scoring()
    score = sum(_weight_for(weights, v) for v in normalized.values())
    return min(int(cap or SCORE_CAP), score)


def level_from_score(score) -> str:
    try:
        score = max(0, int(score))
    except (TypeError, ValueError):
        return "未知"
    _, _, thresholds = _scoring()
    for item in thresholds or LEVEL_THRESHOLDS:
        if isinstance(item, dict):
            limit, level = item.get("limit"), item.get("level")
        else:
            limit, level = item
        if score <= int(limit):
            return level
    return "极难"


def difficulty_from_dims(dims) -> dict:
    normalized = normalize_dims(dims)
    score = score_from_dims(normalized)
    return {
        "level": level_from_score(score),
        "total_score": score,
        "dimensions": normalized,
    }


def step_difficulty_from_dims(dims) -> dict:
    normalized = normalize_dims(dims)
    score = score_from_dims(normalized)
    return {
        "level": level_from_score(score),
        "score": score,
        "dimensions": normalized,
    }


def aggregate_chunk_results(chunk_results: list) -> tuple:
    """重算每个块的难度与整题难度，并回填步骤分/等级。返回 (chunk_results, overall)。"""
    all_vectors = []
    for cr in chunk_results:
        if not isinstance(cr, dict):
            continue
        vectors = []
        for step in cr.get("steps") or []:
            if not isinstance(step, dict):
                continue
            sd = step.get("step_difficulty") or {}
            if not isinstance(sd, dict):
                sd = {}
            dims = normalize_dims(sd.get("dimensions"))
            sd["dimensions"] = dims
            sd["score"] = score_from_dims(dims)
            sd["level"] = level_from_score(sd["score"])
            step["step_difficulty"] = sd
            vectors.append(dims)
        cr["difficulty"] = difficulty_from_dims(aggregate_dims(vectors))
        all_vectors.extend(vectors)
    overall = difficulty_from_dims(aggregate_dims(all_vectors))
    return chunk_results, overall
