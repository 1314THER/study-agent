"""Reviewed, recent medium exam questions for the visitor experience.

Statements are checked against the linked papers. Explanations and difficulty
annotations are prepared locally and must be labelled as prepared examples.
"""
from __future__ import annotations

from copy import deepcopy

DEFAULT_PRESET_ID = "national-2025-q16"
NATIONAL_SOURCE = "https://img.gaokaozhitongche.com/resource/pdf/paper/202510/20251029033732_J2Ceon.pdf"
NATIONAL_2023_SOURCE = "https://gaokaohub.com/paper/2023-xinkebiao-i-math.html"
SHANGHAI_SOURCE = "https://www.bjxhbt.com/m/3a782d7aac49477abb2c1c3401e9453e_20240606111435.pdf"
DIMENSIONS = ["非常规程度", "计算量", "分类讨论", "知识广度", "条件转化难度"]


def _step(number, title, writing, detail, knowledge, *, calculation=0, translation=0, breadth=0):
    dimensions = dict.fromkeys(DIMENSIONS, 0)
    dimensions.update({"计算量": calculation, "条件转化难度": translation, "知识广度": breadth})
    score = sum(dimensions.values())
    return {"step_number": number, "title": title, "step_level1": None,
        "standard_writing": writing, "detailed_writing": detail, "knowledge_point": knowledge,
        "step_difficulty": {"dimensions": dimensions, "score": score, "level": "中等" if score >= 4 else "容易"}}


def _example(preset_id, label, question, paper, year, number, url, category, kind, chunks):
    # Only expand question-part separators; LaTeX commands such as \ne stay intact.
    question = question.replace(r"\n(", "\n(")
    all_steps = [step for chunk in chunks for step in chunk["steps"]]
    dimensions = {key: max(s["step_difficulty"]["dimensions"][key] for s in all_steps) for key in DIMENSIONS}
    difficulty = {"dimensions": dimensions, "total_score": sum(dimensions.values()), "level": "中等"}
    knowledge = list(dict.fromkeys(step["knowledge_point"] for step in all_steps))
    results = []
    for i, chunk in enumerate(chunks, 1):
        vector = {key: max(s["step_difficulty"]["dimensions"][key] for s in chunk["steps"]) for key in DIMENSIONS}
        score = sum(vector.values())
        results.append({"chunk_id": i, "chunk_type": kind, "category": {"level1": category},
            "knowledge_points": list(dict.fromkeys(step["knowledge_point"] for step in chunk["steps"])),
            "difficulty": {"dimensions": vector, "total_score": score, "level": "中等" if score >= 4 else "容易"},
            "steps": chunk["steps"], "final_answer": chunk["answer"]})
    source = {"paper": paper, "year": year, "question_number": number, "url": url}
    result = {"status": "可解", "preset_id": preset_id, "prepared_example": True,
        "result_source": "prepared_example", "source_label": "已准备的演示解析",
        "source_type": "高考题", "source_meta": {"paper_name": paper, "paper": paper,
            "year": year, "question_number": number, "question_no": str(number), "url": url},
        "question": question, "category": {"level1": category}, "question_type": kind,
        "difficulty": deepcopy(difficulty), "final_answer": "；".join(c["answer"] for c in chunks),
        "knowledge_points": knowledge, "overall_difficulty": deepcopy(difficulty), "chunk_results": results,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
    return {"id": preset_id, "label": label, "question": question, "source": source, "answer_json": result}


_PRESETS = [
    _example(
        DEFAULT_PRESET_ID, "2025 全国一卷 · 第 16 题 · 数列与导数",
        r"设数列 $\{a_n\}$ 满足 $a_1=3$，$\frac{a_{n+1}}{n}=\frac{a_n}{n+1}+\frac{1}{n(n+1)}$。\n(1) 证明：$\{na_n\}$ 为等差数列；\n(2) 设 $f(x)=a_1x+a_2x^2+\cdots+a_mx^m$，求 $f'(-2)$。",
        "2025 年高考全国一卷", 2025, 16, NATIONAL_SOURCE, "数列", "数列大题",
        [
            {"answer": "(1) $na_n=n+2$，是首项为 $3$、公差为 $1$ 的等差数列", "steps": [
                _step(1, "化为相邻项差", r"两边乘以 $n(n+1)$，得 $(n+1)a_{n+1}=na_n+1$。令 $b_n=na_n$，则 $b_{n+1}-b_n=1$。",
                    r"递推式中的分母提示把 $n$ 与 $a_n$ 组合成新数列。$b_{n+1}=(n+1)a_{n+1}$，所以相邻两项的差恒为 $1$，符合等差数列的定义。", "等差数列", translation=1),
                _step(2, "得到数列通项", r"$b_1=a_1=3$，故 $b_n=3+(n-1)=n+2$，从而 $a_n=1+\frac2n$。",
                    r"先由等差数列的首项、公差写出 $b_n$，再除以正整数 $n$，得到原数列通项。", "等差数列", calculation=1),
            ]},
            {"answer": r"(2) $f'(-2)=\frac{7-(3m+7)(-2)^m}{9}$", "steps": [
                _step(3, "逐项求导", r"$f'(x)=\sum_{k=1}^{m}ka_kx^{k-1}=\sum_{k=1}^{m}(k+2)x^{k-1}$，故 $f'(-2)=\sum_{k=1}^{m}(k+2)(-2)^{k-1}$。",
                    r"这是有限项多项式，可逐项求导。利用第 (1) 问的 $ka_k=k+2$，把导数的系数改写为等差因子。", "导数的计算", translation=1, breadth=1),
                _step(4, "错位相减求和", r"记 $S=\sum_{k=1}^{m}(k+2)(-2)^{k-1}$。则 $3S=3+\sum_{k=1}^{m-1}(-2)^k-(m+2)(-2)^m$。",
                    r"把 $S$ 乘以 $-2$，指数整体提高一次。将 $S-(-2S)$ 相减：首项留下 $3$，中间每项的系数差为 $1$，末项留下 $-(m+2)(-2)^m$。", "数列求和", calculation=2, translation=2, breadth=1),
                _step(5, "化简并检查首项情形", r"$\sum_{k=1}^{m-1}(-2)^k=\frac{(-2)^m+2}{-3}$，所以 $S=\frac{7-(3m+7)(-2)^m}{9}$。",
                    r"把中间等比和代入，通分可得 $3S=[7-(3m+7)(-2)^m]/3$，再除以 $3$。当 $m=1$ 时答案为 $3$；当 $m=2$ 时为 $-5$，均与直接求导相符。", "数列求和", calculation=1),
            ]},
        ],
    ),
    _example(
        "national-2023-q17", "2023 新课标全国Ⅰ卷 · 第 17 题 · 解三角形",
        r"已知在 $\triangle ABC$ 中，$A+B=3C$，$2\sin(A-C)=\sin B$。\n(1) 求 $\sin A$；\n(2) 设 $AB=5$，求 $AB$ 边上的高。",
        "2023 年新课标全国Ⅰ卷", 2023, 17, NATIONAL_2023_SOURCE, "三角函数", "解三角形大题",
        [
            {"answer": r"(1) $\sin A=\frac{3}{\sqrt{10}}$", "steps": [
                _step(1, "先由内角关系确定角 C", r"由 $A+B+C=\pi$ 及 $A+B=3C$，得 $4C=\pi$，所以 $C=\frac{\pi}{4}$。",
                    r"三角形内角和给出 $A+B+C=\pi$，题设又给 $A+B=3C$。代入后得到 $4C=\pi$，因此 $C=\pi/4$。", "解三角形", translation=1),
                _step(2, "用和差角公式求 sin A", r"$B=\frac{3\pi}{4}-A$。代入 $2\sin(A-\frac{\pi}{4})=\sin(\frac{3\pi}{4}-A)$，得 $2(\sin A-\cos A)=\sin A+\cos A$，即 $\sin A=3\cos A$。因 $0<A<\pi$ 且 $\tan A=3>0$，故 $A$ 为锐角，$\sin A=\frac{3}{\sqrt{10}}$。",
                    r"由 $B=3\pi/4-A$，分别展开两边的正弦。整理可得 $\sin A=3\cos A$，即 $\tan A=3$。结合 $A$ 是三角形内角，得到 $A=\arctan 3$，从而 $\sin A=3/\sqrt{10}$。", "三角恒等变换", calculation=1, translation=1),
            ]},
            {"answer": r"(2) $AB$ 边上的高为 $6$", "steps": [
                _step(3, "先求角 B 的正弦值", r"$\sin B=\sin(\frac{3\pi}{4}-A)=\frac{\sqrt2}{2}(\sin A+\cos A)=\frac{2}{\sqrt5}$。",
                    r"由第 (1) 问可得 $\sin A=3/\sqrt{10}$、$\cos A=1/\sqrt{10}$。将 $B=3\pi/4-A$ 代入正弦差角公式，即得 $\sin B=2/\sqrt5$。", "三角恒等变换", calculation=1),
                _step(4, "用正弦定理和面积求高", r"由正弦定理，$AC=\frac{AB\sin B}{\sin C}$。设 $AB$ 边上的高为 $h$，则 $h=AC\sin A=\frac{5\cdot\frac{2}{\sqrt5}\cdot\frac{3}{\sqrt{10}}}{\frac{\sqrt2}{2}}=6$。",
                    r"以 $AB=5$ 为底，利用正弦定理表示边 $AC$，再用 $h=AC\sin A$ 求高。代入 $\sin B=2/\sqrt5$、$\sin A=3/\sqrt{10}$、$\sin C=\sqrt2/2$，化简得到 $h=6$。", "解三角形", calculation=1, translation=1),
            ]},
        ],
    ),
    _example(
        "shanghai-2024-q18", "2024 上海卷 · 第 18 题 · 对数函数",
        r"已知函数 $f(x)=\log_a x$，其中 $a>0$ 且 $a\ne1$。\n(1) 已知 $y=f(x)$ 的图象过点 $(4,2)$，求不等式 $f(2x-2)<f(x)$ 的解集；\n(2) 存在实数 $x$，使得 $f(x+1)$、$f(ax)$、$f(x+2)$ 成等差数列，求 $a$ 的取值范围。",
        "2024 年上海市高考数学试卷", 2024, 18, SHANGHAI_SOURCE, "指对幂耐克函数", "函数与导数大题",
        [
            {"answer": "(1) 不等式的解集为 $(1,2)$", "steps": [
                _step(1, "由已知点确定底数", r"$f(4)=2$，即 $\log_a4=2$，所以 $a^2=4$。由 $a>0$ 得 $a=2$。",
                    "利用对数与指数的互相转换：底数的二次方等于真数。由于对数底数必须为正，只保留正根 2。", "对数函数", translation=1),
                _step(2, "同时处理真数条件与单调性", r"$2x-2>0$ 且 $x>0$，得 $x>1$。底数 $2>1$，对数函数递增，因此 $2x-2<x$，即 $x<2$。取交集得 $1<x<2$。",
                    "先保证两边的真数都为正，不能只比较真数而忘记定义域。递增函数保持不等号方向。最后把单调性得到的条件与定义域条件求交集。", "对数函数", calculation=1, translation=1),
            ]},
            {"answer": r"(2) $a\in(1,+\infty)$", "steps": [
                _step(3, "把等差关系转为参数方程", r"由 $ax>0$ 及 $a>0$，得 $x>0$。等差关系给出 $2\log_a(ax)=\log_a(x+1)+\log_a(x+2)$，故 $a^2x^2=(x+1)(x+2)$，即 $a^2=1+\frac3x+\frac2{x^2}$。",
                    r"三个真数都必须为正，其中 $ax>0$ 已经推出 $x>0$，这也保证 $x+1$、$x+2$ 为正。由等差数列中项的两倍等于两端之和，合并对数后利用对数函数的一一对应性，使真数相等。", "对数的运算", calculation=1, translation=2, breadth=1),
                _step(4, "先得到必要条件", r"对 $x>0$，$1+\frac3x+\frac2{x^2}>1$，因此 $a^2>1$。结合 $a>0$，得 $a>1$。",
                    "正的 x 使两个分式项均为正。因此参数平方严格大于 1，正底数只能大于 1。还需要证明每个 a>1 都确实能找到合适的 x。", "函数的值域", translation=1),
                _step(5, "证明每个候选参数都能取到", r"令 $g(x)=1+\frac3x+\frac2{x^2}$，$x>0$。有 $g'(x)=-\frac3{x^2}-\frac4{x^3}<0$，且 $\lim_{x\to0^+}g(x)=+\infty$，$\lim_{x\to+\infty}g(x)=1$，故值域为 $(1,+\infty)$。",
                    "g 在正半轴连续且严格递减，从任意大的正值下降并趋近于 1，所以下方端点不能取到，但每个大于 1 的值都能取到。这就证明必要条件也是充分条件。", "导数与函数的单调性", calculation=1, translation=2, breadth=1),
                _step(6, "完成充分性并给出范围", r"任取 $a>1$，$a^2\in(1,+\infty)$，因此存在 $x>0$ 使 $g(x)=a^2$，反推三个函数值成等差数列。故 $a\in(1,+\infty)$。",
                    "所找到的正 x 自动满足三个对数真数的条件；前面的变形均可逆。因此既证明了 a 必须大于 1，也证明了每个 a>1 都满足存在性要求。", "函数的值域", translation=1),
            ]},
        ],
    ),
]
_BY_ID = {item["id"]: item for item in _PRESETS}


def get_preset(preset_id):
    """Return an independently mutable complete example, or None."""
    return deepcopy(_BY_ID.get(preset_id))


def list_presets():
    return {"default_id": DEFAULT_PRESET_ID, "presets": public_presets()}


def public_presets():
    return [{key: deepcopy(item[key]) for key in ("id", "label", "question", "source")} for item in _PRESETS]


def prepared_result(preset_id):
    item = get_preset(preset_id)
    return item["answer_json"] if item else None
