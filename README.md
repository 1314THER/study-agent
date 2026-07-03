# 你好，我是张雪峰老师

面向高中生的AI数学解题系统。

---

## 工程进度

### ✅ 已完成

| 版本 | 内容 |
|------|------|
| **V0.1** | 三段式AI处理（Solver → Verifier → Formatter），输入题目返回结构化分步答案 |
| **V0.2** | SQLite 小题库，同题复用秒出结果 |
| **V0.3** | **分块解题系统**：Solver 自动切块 → 逐块专精 Verify + Format → 聚合展示 |

### V0.3 核心改动

- **Solver 自带切块**：多问题目每问一块、选择题每选项一块、填空题每空一块、单题一块
- **专精 Verifier**：8 个大题板块各有独立 verifier prompt（解析几何、立体几何、数列、函数与导数、三角函数与解三角形、概率与统计、新定义题、交叉压轴题），另有选择题/填空题专用 verifier
- **题型选择器**：前端按钮可选"自动识别 / 选择题 / 填空题 / 大题"
- **知识点硬编码**：知识点由 `categories.py` 唯一数据源，verifier prompt 运行时注入，不依赖 AI 判断
- **进度条**：分步调用，实时显示百分比和 token 消耗
- **多问分组**：子问步骤按 (1)(2)(3) 分组展示，答案独立块显示
- **Formatter 简化**：纯机械解析 + 轻量 AI 难度评分 + JSON 纠错

### 📋 待完成

| 优先级 | 内容 | 说明 |
|--------|------|------|
| **P0** | Verifier prompt 定制 | 各板块检查清单和知识点列表需进一步打磨 |
| **P1** | V0.4 手把手教学 | 分步互动教学，学生输入 → AI 比对反馈 → 错因分类 |
| **P1** | V0.5 智能刷题 | AI 出题 → 学生作答 → AI 批改 → 练习报告 |
| **P2** | V1.0 录屏分析 | 上传录屏 → 拆帧 → OCR → 标准答案对比 → 分析报告 |

---

## 项目结构

```
study-agent/
├── backend/
│   ├── main.py              # FastAPI 服务器，三个入口
│   ├── solver.py            # 核心：切块 + 路由 + 解析 + 聚合
│   ├── database.py          # SQLite 小题库
│   ├── categories.py        # 知识点分类（唯一数据源）
│   ├── prompts/
│   │   ├── solver.md        # Solver 提示词（含切块规则+板块列表）
│   │   ├── formatter.md     # Formatter 提示词（难度评分+JSON纠错）
│   │   └── verifiers/
│   │       ├── 解析几何.md
│   │       ├── 立体几何.md
│   │       ├── 数列.md
│   │       ├── 函数与导数.md
│   │       ├── 三角函数与解三角形.md
│   │       ├── 概率与统计.md
│   │       ├── 新定义题.md
│   │       ├── 交叉压轴题.md
│   │       ├── 选择题.md
│   │       ├── 填空题.md
│   │       └── fallback.md
│   └── __init__.py
├── frontend/
│   └── index.html           # 前端页面（题型选择器+进度条+块卡片）
├── requirements.txt
├── .env                      # DEEPSEEK_API_KEY
├── .gitignore
└── README.md
```

---

## 数据结构

### categories.py（唯一数据源）

```python
CATEGORIES = {
    "解析几何": ["直线与圆", "椭圆", "双曲线", "抛物线", ...],
    "函数与导数": ["函数概念与性质", "导数运算", "单调性与极值", ...],
    # 共 8 个大题板块，每个板块有对应的 verifier prompt
}
```

### 数据库 questions 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 自增主键 |
| `content` | TEXT | 题目原文（唯一） |
| `answer_json` | TEXT | 完整结构化答案（JSON） |
| `category_level1` | TEXT | 一级分类 |
| `category_level2` | TEXT | 二级分类 |
| `difficulty_level` | TEXT | 容易/中等/困难/极难 |
| `difficulty_score` | INTEGER | 总分 0-12 |
| `difficulty_dimensions` | TEXT | 六维度得分（JSON） |
| `common_mistakes` | TEXT | 常见错误（JSON） |
| `knowledge_points` | TEXT | 知识点列表（JSON） |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

---

## 工作流

```
题目 → solver.md（切块+解答） → _parse_chunks 分割
  ├─ 块1 → 专精 Verifier → Formatter → 结果卡片
  ├─ 块2 → 专精 Verifier → Formatter → 结果卡片
  └─ ...
  ↓ 聚合 → 前端卡片展示
```

进度：step1 完成 78% → 逐块校验（保持 78%）→ 全部完成 91% → 展示 100%

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/solve/step1` | 切块+解答，返回 chunks |
| POST | `/solve/step2` | 校验+格式化一个块 |
| POST | `/solve` | 全量一次完成 |
| GET | `/questions` | 查看历史题目 |
| GET | `/categories` | 获取分类列表 |

## 启动

```bash
cd study-agent
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

后端运行在 http://127.0.0.1:8000。打开 `frontend/index.html` 即可使用。

（需要设置 `.env` 中的 `DEEPSEEK_API_KEY`）
