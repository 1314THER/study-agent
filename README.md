# 数学最强大脑 v1.0（最终版）

面向高中生的 AI 数学解题系统。基于 DeepSeek V4，三段流水线 + 四老师配置 + 五维难度评分 + 小题库。

---

> **v1.0 最终版** — 2026-07-05。功能稳定，不再主动开发。

### 核心流程

```
用户输入题目
  → Solver（解答 + 板块分类 + 状态判断）
  → Verifier（分块 + 标准过程 + 详细过程 + 难度评分）
  → Formatter（一致性校验 + LaTeX 检查 + 聚合）
  → 前端展示（步骤卡片 + 雷达图 + 整体难度）
```

### 四老师系统

| 老师 | Solver 模型 | Verifier 模型 | Formatter 模型 | UI 主题 |
|------|------------|--------------|---------------|---------|
| 🫅 梁梁 | v4-flash | v4-flash | v4-flash | 黄色 |
| 🎩 韬韬 | v4-pro (low) | v4-flash | v4-flash | 粉色 |
| 🏃 雪峰 | v4-pro (high) | v4-flash | v4-flash | 紫色 |
| 🐔 鸡 | v4-pro (high) | v4-pro (high) | v4-pro (high) | 绿色 |

进度消息会显示对应老师名称（"梁梁 正在思考""雪峰 正在分类知识点"等），前端主题色跟随老师切换。

### 步骤数据结构

每个步骤包含三层：

| 字段 | 内容 | 展示 |
|------|------|------|
| `title` | 一句概括 | 和步骤号同行 |
| `standard_writing` | 保留关键公式的推导路径（阅卷人可只看这个给满分） | 默认显示 |
| `detailed_writing` | 原始解答裁切，不修改内容。保护 $...$、$$...$$ 和 \begin{...}...\end{...} 边界 | 点击展开 |

### 难度评分（5 维度 x 0-3 分，总分 0-15）

| 维度 | 说明 |
|------|------|
| 常规程度 | 思路直白 → 非常隐蔽 |
| 计算量 | 心算 → 7步以上 |
| 理解难度 | 题意直白 → 非常绕 |
| 分类讨论 | 无需 → 4种以上 |
| 涉及到的知识点数量 | 1-2个 → 7个及以上 |

### 状态检查

Solver 在输出开头写死结构化状态：

```
###板块###
题型：选择题/填空题/大题
板块：解析几何/数列/...
状态：可解
是否数学题：是/否
是否错题：是/否
是否能做出来：是/否
```

非数学题/不会做/错题 → 直接**雪碧了**，不走后续步骤。

### 进度与计时器

- 自动计时，显示 `已思考 n s/180s`
- 超过 180 秒后去掉分母，另起一行加：你做不过我你信吗
- 三步进度百分比：13% → 78% → 91%（硬编码，有意为之）
- 计时器累计不归零

### 入库清洗

所有结构化字段入库前经过合法性校验（防止 model 输出脏数据）：

| 字段 | 清洗规则 |
|------|---------|
| `category_level1` | 必须在 CATEGORIES 的 key 里 |
| `category_level2` | 必须在 CATEGORIES[level1] 的子列表里 |
| `difficulty_level` | 必须是 容易/中等/困难/极难 之一 |
| `difficulty_dimensions` 的 key | 必须是 5 个维度之一 |
| `knowledge_points` | 必须在 CATEGORIES[level1] 的子列表里 |

---

## 项目结构

```
study-agent/
├── backend/
│   ├── main.py              # FastAPI 服务器
│   ├── solver.py            # 核心：TEACHER_CONFIG + 三步调用 + 解析 + 清洗
│   ├── database.py          # SQLite 小题库 + 入库清洗（含雪碧了）
│   ├── categories.py        # 知识点分类字典（唯一数据源）
│   ├── prompts/
│   │   ├── solver.md        # Solver 提示词（含 ###板块### 硬编码格式）
│   │   ├── formatter.md     # Formatter 提示词（含 LaTeX 检查）
│   │   └── verifiers/
│   │       ├── 解析几何.md
│   │       ├── 立体几何.md
│   │       ├── 数列.md
│   │       ├── 函数与导数.md
│   │       ├── 三角函数与解三角形.md
│   │       ├── 概率与统计.md
│   │       ├── 非常规压轴题.md
│   │       ├── 选择题.md
│   │       └── 填空题.md
│   └── __init__.py
├── frontend/
│   └── index.html           # 前端（老师选择器 + 进度条 + 计时器 + 步骤卡片 + 雷达图）
├── study_agent.db           # SQLite（自动创建）
├── requirements.txt
├── .env                      # DEEPSEEK_API_KEY（已 .gitignore）
├── .gitignore
└── README.md
```

---

## 数据结构

### categories.py

```python
CATEGORIES = {
    "解析几何": ["直线与圆", "椭圆", "双曲线", "抛物线", "直线与圆锥曲线", "弦长与面积", "轨迹方程", "极点极线"],
    "立体几何": ["空间位置关系", "平行与垂直证明", "空间角与距离", "空间向量", "几何体体积与表面积"],
    "数列": ["等差数列", "等比数列", "数列求和", "数列递推", "数列综合"],
    "函数与导数": ["函数概念与性质", "指数函数", "对数函数", "幂函数", "函数图像", "函数方程", "导数运算", "单调性与极值", "切线问题", "隐零点与极值点偏移", "导数综合"],
    "三角函数与解三角形": ["三角恒等变换", "三角函数图像与性质", "解三角形"],
    "概率与统计": ["排列组合", "二项式定理", "概率", "统计", "条件概率与全概率"],
    "非常规压轴题": ["新定义理解", "新运算规则", "新概念应用", "多板块综合", "信息迁移", "创新题型"],
}
```

### 数据库 questions 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | TEXT | 题目原文（唯一） |
| `answer_json` | TEXT | 完整结构化答案（JSON blob） |
| `category_level1` | TEXT | 一级分类（清洗后） |
| `category_level2` | TEXT | 二级分类（清洗后） |
| `difficulty_level` | TEXT | 容易/中等/困难/极难 |
| `difficulty_score` | INTEGER | 0-15 |
| `difficulty_dimensions` | TEXT | 五维度得分（JSON） |
| `knowledge_points` | TEXT | 知识点列表（JSON，清洗后） |
| `common_mistakes` | TEXT | 预留 |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

---

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/solve/step1` | Solver：解答 + 板块提取 + 雪碧了检测 |
| POST | `/solve/step2` | Verifier：分块 + 标准过程 + 步骤难度 + 块难度 |
| POST | `/solve/step3` | Formatter：全局校验 + LaTeX 边界检查 + 聚合 |
| POST | `/solve` | 三步合成一个接口（带缓存） |
| GET | `/` | 状态检查 |
| GET | `/questions` | 历史题目 |
| GET | `/categories` | 板块分类列表 |

所有接口都接受可选 `teacher` 参数：`liangliang` / `taotao` / `xuefeng` / `ji`。默认梁梁。

---

## 启动

```bash
cd study-agent
pip install -r requirements.txt
# 设置 .env: DEEPSEEK_API_KEY=sk-xxx
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

后端运行在 http://127.0.0.1:8000。用浏览器打开 `frontend/index.html` 即可使用。

---

## v1.0 变更记录

- **Solver 状态检测**：修复 Solver 输出带方括号（`[不会做]`）时状态无法被代码识别的问题
- **维度对齐**：所有 verifier prompt、数据库清洗（`_VALID_DIMENSION_KEYS`）、前端雷达图统一为 5 维度（常规程度 / 计算量 / 理解难度 / 分类讨论 / 涉及到的知识点数量），每维 0-3 分
- **LaTeX 边界保护**：Verifier 裁切步骤时保护 `$...$`、`$$...$$` 和 `\begin{...}...\end{...}` 不被从中截断
- **多行环境要求**：Solver 输出 `align` / `cases` / `matrix` 等环境必须用 `$$` 包裹，防止前端 KaTeX 渲染失败
- **前端进度显示**：各步骤显示对应老师名称（"梁梁 正在思考"），计时上限改为 180s，超时后显示"你做不过我你信吗"
- **雷达图重写**：HiDPI（Retina）支持、径向渐变填充、自适应标签对齐、5 轴显示
- **fix**: 移除 `main.py` 中重复注册的 `/solve/step2` 路由
