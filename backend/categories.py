"""
知识点分类（固定列表，AI 从中选择）
调整时直接改 CATEGORIES 字典即可，不需要动其他代码。
"""

CATEGORIES = {
    "集合与逻辑": ["集合运算", "命题逻辑", "充分必要条件"],
    "不等式": ["不等式性质", "一元二次不等式", "基本不等式", "含参不等式"],
    "函数": ["函数概念与性质", "指数函数", "对数函数", "幂函数", "函数图像", "函数综合"],
    "导数": ["导数运算", "单调性与极值", "切线问题", "导数综合"],
    "三角函数与解三角形": ["三角恒等变换", "三角函数图像与性质", "解三角形"],
    "平面向量": ["向量运算", "向量几何应用"],
    "数列": ["等差数列", "等比数列", "数列求和", "数列综合"],
    "立体几何": ["空间位置关系", "平行与垂直", "空间角与距离", "空间向量"],
    "解析几何": ["直线与圆", "椭圆", "双曲线", "抛物线", "直线与圆锥曲线", "极点极线"],
    "概率与统计": ["排列组合", "二项式定理", "概率", "统计"],
    "复数": ["复数运算", "复数几何意义"],
}


def get_all_categories():
    """返回完整分类列表给前端"""
    return [
        {"level1": k, "level2_list": v}
        for k, v in CATEGORIES.items()
    ]


def validate_category(level1: str, level2: str) -> bool:
    """校验 AI 选的一二级分类是否在列表内"""
    if level1 not in CATEGORIES:
        return False
    return level2 in CATEGORIES[level1]


def format_category_prompt() -> str:
    """生成一段供 formatter.md 嵌入的分类提示"""
    lines = ["可选知识点分类（请从以下列表中选取，不要自己创造）："]
    for l1, l2_list in CATEGORIES.items():
        lines.append(f"  {l1} → {'、'.join(l2_list)}")
    return "\n".join(lines)
