"""
知识点分类（唯一数据源，按高考大题题型分类）
非常规压轴题合并了原交叉压轴题和新定义题。
选择题和填空题走专精 verifier，不参与板块路由。
"""

CATEGORIES = {
    "解析几何": [
        "直线与圆", "椭圆", "双曲线", "抛物线",
        "直线与圆锥曲线", "弦长与面积", "轨迹方程", "极点极线",
    ],
    "立体几何": [
        "空间位置关系", "平行与垂直证明", "空间角与距离",
        "空间向量", "几何体体积与表面积",
    ],
    "数列": [
        "等差数列", "等比数列", "数列求和", "数列递推", "数列综合",
    ],
    "函数与导数": [
        "函数概念与性质", "指数函数", "对数函数", "幂函数",
        "函数图像", "函数方程",
        "导数运算", "单调性与极值", "切线问题",
        "隐零点与极值点偏移", "导数综合",
    ],
    "三角函数与解三角形": [
        "三角恒等变换", "三角函数图像与性质", "解三角形",
    ],
    "概率与统计": [
        "排列组合", "二项式定理", "概率", "统计", "条件概率与全概率",
    ],
    "非常规压轴题": [
        "新定义理解", "新运算规则", "新概念应用",
        "多板块综合", "信息迁移", "创新题型",
    ],
}

VALID_QUESTION_TYPES = ["选择题", "填空题", "大题"]


def get_all_categories():
    return [{"level1": k, "level2_list": v} for k, v in CATEGORIES.items()]


def solver_prompt_snippet() -> str:
    lines = ["可选板块（仅大题需要选择，选择题和填空题直接写题型即可）："]
    for l1, l2_list in CATEGORIES.items():
        lines.append(f"  {l1} -> {'、'.join(l2_list)}")
    return "\n".join(lines)


def verify_prompt_knowledge_points(level1: str) -> str:
    if level1 not in CATEGORIES:
        raise ValueError(f"未知板块：{level1}")
    items = "、".join(CATEGORIES[level1])
    return f"可选知识点（请从以下列表中选取，不要自己创造）：\n{items}"


def get_knowledge_points(level1: str) -> list:
    return CATEGORIES.get(level1, [])


def validate_knowledge_points(level1: str, points: list) -> list:
    valid = set(CATEGORIES.get(level1, []))
    return [p for p in points if p in valid]
