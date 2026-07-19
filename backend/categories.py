"""
知识点分类（从 categories.yaml 动态加载）
"""
import os
import yaml


def _load_categories():
    path = os.path.join(os.path.dirname(__file__), "categories.yaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # 扁平化为 2 级：板块 -> [子板块列表]
    return {k: list(v.keys()) for k, v in data.items()}


CATEGORIES = _load_categories()


def get_all_categories():
    return [{"level1": k, "level2_list": v} for k, v in CATEGORIES.items()]


def solver_prompt_snippet() -> str:
    lines = ["可选板块："]
    for l1, l2_list in CATEGORIES.items():
        lines.append(f"  {l1} -> {'、'.join(l2_list)}")
    return "\n".join(lines)


def verify_prompt_knowledge_points(level1: str) -> str:
    if level1 not in CATEGORIES:
        raise ValueError(f"未知板块：{level1}")
    items = "、".join(CATEGORIES[level1])
    return f"可选知识点（请严格从以下列表中选取，不要自己创造）：\n{items}"


def get_knowledge_points(level1: str) -> list:
    return CATEGORIES.get(level1, [])


def validate_knowledge_points(level1: str, points: list) -> list:
    valid = set(CATEGORIES.get(level1, []))
    return [p for p in points if p in valid]
