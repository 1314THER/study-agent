"""
步骤表加载模块
从 steps.yaml 加载题型→一级步骤→二级步骤的结构
"""

import os
import yaml

_STEPS_PATH = os.path.join(os.path.dirname(__file__), "steps.yaml")
_steps_cache = None

def _load_steps():
    """加载 steps.yaml，返回 dict"""
    global _steps_cache
    if _steps_cache is not None:
        return _steps_cache
    if not os.path.exists(_STEPS_PATH):
        _steps_cache = {}
        return _steps_cache
    with open(_STEPS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    _steps_cache = data or {}
    return _steps_cache


def get_all_question_types():
    """返回所有题型名称列表"""
    return list(_load_steps().keys())


def get_step_structure(qtype: str) -> dict:
    """
    返回某题型的两级步骤结构
    空类型返回 {}
    """
    data = _load_steps()
    return data.get(qtype, {}) or {}


def has_predefined_steps(qtype: str) -> bool:
    """判断某题型是否有预定义步骤名"""
    steps = get_step_structure(qtype)
    return bool(steps)


def get_all_level1_names(qtype: str) -> list:
    """返回某题型的所有一级步骤名（二级步骤）"""
    return list(get_step_structure(qtype).keys())


def get_level2_names(qtype: str, level1: str) -> list:
    """返回某二级步骤下的所有具体步骤名"""
    steps = get_step_structure(qtype)
    return steps.get(level1, [])


def get_all_level2_names(qtype: str) -> list:
    """返回某题型所有具体步骤名（平铺）"""
    result = []
    for level1, level2_list in get_step_structure(qtype).items():
        result.extend(level2_list)
    return result


def format_step_prompt_snippet(qtype: str) -> str:
    """
    生成嵌入到 verifier prompt 中的步骤名段落
    空类型返回空字符串
    """
    structure = get_step_structure(qtype)
    if not structure:
        return ""
    lines = [
        "## 步骤名选择（请严格遵守）",
        "",
        "本题型必须从以下步骤名中选择，不要自己创造。",
        "一级步骤（二级步骤名）与具体步骤名的对应关系如下：",
        "",
    ]
    for level1, level2_list in structure.items():
        if level2_list:
            items = " / ".join(level2_list)
            lines.append(f"- {level1}：{items}")
        else:
            lines.append(f"- {level1}")
    lines.append("")
    lines.append("每个步骤必须同时输出所属的一级步骤名（二级步骤）：")
    lines.append("")
    lines.append("步骤N：<一体步骤名>")
    lines.append("标准过程：...")
    lines.append("详细过程：...")
    lines.append("二级步骤：<二级步骤名>")
    lines.append("知识点：...")
    lines.append("步骤难度：...")
    return "\n".join(lines)


def clear_cache():
    """清除缓存（用于测试或热重载）"""
    global _steps_cache
    _steps_cache = None
