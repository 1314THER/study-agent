# 成为数学高手 — AI 学习伴侣

面向高中生的 AI 数学学习系统。基于 DeepSeek V4，三段流水线 + 四老师配置 + 五维难度评分 + 错题本。

---

## 核心流程

```
用户输入题目
  → Solver（解答 + 板块分类 + 雪碧了检测）
  → Verifier（分块 + 标准过程 + 详细过程 + 难度评分）
  → Formatter（一致性校验 + LaTeX 检查 + 聚合）
  → 前端展示（步骤卡片 + 雷达图 + 整体难度）
  → 可选项：保存到错题本（搜前开关 / 搜后按钮）
  → 错题本可回看完整解析
```

---

## 四老师系统

| 老师 | Solver 模型 | Verifier 模型 | Formatter 模型 | UI 主题 | 描述 |
|------|------------|--------------|---------------|---------|------|
| 🫅 梁梁 | v4-flash | v4-flash | v4-flash | 黄色 | 快速，但是可能出错 |
| 🎩 韬韬 | v4-pro (low) | v4-flash | v4-flash | 粉色 | 更慢但更聪明 |
| 🏃 雪峰 | v4-pro (high) | v4-flash | v4-flash | 紫色 | 嘴唇有点紫的老师 |
| 🐔 鸡 | v4-pro (high) | v4-pro (high) | v4-pro (high) | 绿色 | 每一步都要考虑半天 |

进度消息会显示对应老师名称，前端主题色跟随老师切换。

---

## 前端页面

| 页面 | 文件 | 说明 |
|------|------|------|
| 和老师对答案 | `frontend/index.html` | 搜题 + 分步展示 + 保存开关 |
| 老师手把手教你做题 | `frontend/teach.html` | 手把手教学（预留，V0.3 第二阶段） |
| 错题本 | `frontend/history.html` | 历史题目列表 + 详情（含雷达图） |

所有页面共享 `frontend/style.css`，左侧导航栏 72px。

### 特性

- **保存到错题本**：搜前开关默认勾选，自动入库；搜完后也可手动点击"加入到错题本"按钮
- **去重**：同一个题目不会重复保存
- **页面记忆**：localStorage 持久化老师选择、输入框内容、保存开关状态、上次结果
- **时区**：显示 UTC+8 时间
- **KaTeX 渲染**：列表预览和详情中的 LaTeX 公式自动渲染

---

## 步骤数据结构

每个步骤包含三层：

| 字段 | 内容 | 展示 |
|------|------|------|
| `title` | 一句概括 | 和步骤号同行 |
| `standard_writing` | 保留关键公式的推导路径 | 默认显示 |
| `detailed_writing` | 原始解答裁切，保护 `$...$`、`$$...$$` 和 `\begin{...}...\end{...}` 边界 | 点击展开 |

---

## 难度评分（5 维度 x 0-3 分，总分 0-15）

| 维度 | 说明 |
|------|------|
| 非常规程度 | 思路直白 → 非常隐蔽 |
| 计算量 | 心算 → 7步以上 |
| 理解难度 | 题意直白 → 非常绕 |
| 分类讨论 | 无需 → 4种以上 |
| 知识点密度 | 1-2个 → 7个及以上 |

---

## 项目结构

```
study-agent/
├── backend/
│   ├── main.py              # FastAPI 服务器（路由 + 接口）
│   ├── solver.py            # 核心：TEACHER_CONFIG + 三步调用 + 解析 + 清洗
│   ├── database.py          # SQLite 小题库 + 入库清洗 + 增删查
│   ├── categories.py        # 知识点分类字典（唯一数据源）
│   ├── prompts/
│   │   ├── solver.md        # Solver 提示词（含 ###板块### 硬编码格式）
│   │   ├── formatter.md     # Formatter 提示词（含 LaTeX 检查）
│   │   └── verifiers/       # 9 个板块级 Verifier prompt
│   └── __init__.py
├── frontend/
│   ├── style.css            # 公共样式（侧边栏 + 卡片 + 步骤 + 雷达图等）
│   ├── index.html           # 搜题做题页（老师选择 + 搜索 + 保存开关 + 结果展示）
│   ├── teach.html           # 手把手教学·预留
│   └── history.html         # 错题本（列表 + 详情双视图）
├── study_agent.db           # SQLite（自动创建）
├── requirements.txt
├── .env                     # DEEPSEEK_API_KEY（已 .gitignore）
├── .gitignore
├── start.sh                 # 启动后端
├── stop.sh                  # 停止后端
└── README.md
```

---

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/solve/step1` | Solver：解答 + 板块提取 + 雪碧了检测 |
| POST | `/solve/step2` | Verifier：分块 + 标准过程 + 步骤难度 + 块难度 |
| POST | `/solve/step3` | Formatter：全局校验 + LaTeX 检查 + 聚合 + 可选入库（`save` 参数） |
| POST | `/questions/save` | 手动保存题目到错题本（带去重） |
| GET | `/questions` | 错题本列表（题目摘要 + 分类 + 难度） |
| GET | `/questions/{id}` | 单题完整记录（含 `answer_json`） |
| GET | `/categories` | 知识点分类列表 |
| GET | `/` | 状态检查 |

所有接口都接受可选 `teacher` 参数：`liangliang` / `taotao` / `xuefeng` / `ji`，默认梁梁。

`/solve/step3` 可选 `save` 参数（`true/false`），控制在搜题时同步保存到错题本。

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
| `id` | INTEGER | 自增主键 |
| `content` | TEXT | 题目原文（唯一，UNIQUE） |
| `answer_json` | TEXT | 完整结构化答案（JSON blob，含 steps / chunk_results / overall_difficulty 等） |
| `category_level1` | TEXT | 一级分类（清洗后，取自 CATEGORIES key） |
| `category_level2` | TEXT | 二级分类（清洗后，取自 CATEGORIES[level1]） |
| `difficulty_level` | TEXT | 容易/中等/困难/极难 |
| `difficulty_score` | INTEGER | 0-15 |
| `difficulty_dimensions` | TEXT | 五维度得分 JSON（非常规程度/计算量/理解难度/分类讨论/知识点密度） |
| `knowledge_points` | TEXT | 知识点列表 JSON（清洗后） |
| `common_mistakes` | TEXT | 预留 |
| `created_at` | TIMESTAMP | 创建时间（UTC，前端显示 UTC+8） |
| `updated_at` | TIMESTAMP | 更新时间 |

### 入库清洗

所有结构化字段入库前经过合法性校验：

| 字段 | 清洗规则 |
|------|---------|
| `category_level1` | 必须在 CATEGORIES 的 key 里 |
| `category_level2` | 必须在 CATEGORIES[level1] 的子列表里 |
| `difficulty_level` | 必须是 容易/中等/困难/极难 之一 |
| `difficulty_dimensions` 的 key | 必须是 5 个维度之一 |
| `knowledge_points` | 必须在 CATEGORIES[level1] 的子列表里 |

---

## 启动

```bash
cd study-agent
pip install -r requirements.txt
# 设置 .env: DEEPSEEK_API_KEY=sk-xxx
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

后端运行在 `http://127.0.0.1:8000`。浏览器打开以下页面：

| 页面 | 地址 |
|------|------|
| 和老师对答案 | `frontend/index.html` |
| 手把手教学 | `frontend/teach.html` |
| 错题本 | `frontend/history.html` |

---

## 版本规划

| 版本 | 内容 | 状态 |
|------|------|------|
| V0.1 | 做题系统基础版（Solver / Verifier / Formatter） | ✅ 完成 |
| V0.2 | 单用户小题库 + 入库清洗 | ✅ 完成 |
| V0.3 第一阶段 | 前端三页 + 侧边栏 + 入库控制 + 错题本 + 页面记忆 | ✅ 完成 |
| V0.3 第二阶段 | 手把手教学（干扰项生成 + 选择题交互 + E 路径） | 🚧 待开发 |
| V0.4 | 智能刷题 / 出题系统 | 📋 规划中 |

### V0.3 第一阶段改动记录

- **前端重构**: 单页拆为三页（搜题 / 教学·预留 / 错题本），共享 `style.css`
- **侧边栏导航**: 左侧 72px 深色导航栏，主题色跟随老师切换
- **入库控制**: 搜前开关 + 搜后按钮，双重方式保存到错题本，自动去重
- **错题本**: 列表（摘要 + 标签 + KaTeX 预览）+ 详情（题文 + 分步答案 + 雷达图）
- **页面记忆**: localStorage 持久化老师选择、输入、结果、开关状态
- **五维标签**: "常规程度" → "非常规程度"，"涉及到的知识点数量" → "知识点密度"
- **雷达图**: 画布加宽至 400px，解决标签截断问题
- **时区**: 显示 UTC+8 时间
- **JSON 序列化**: 修复 `api_step3` JSON 解析错误
- **移除 `/solve`**: 统一使用 step1/step2/step3 三阶接口

### V1.0 变更记录（V0.3 之前）

- **Solver 状态检测**：修复 Solver 输出带方括号时状态无法被识别的问题
- **维度对齐**：所有 verifier prompt、数据库清洗、前端雷达图统一为 5 维度，每维 0-3 分
- **LaTeX 边界保护**：Verifier 裁切步骤时保护公式边界不被截断
- **多行环境要求**：Solver 输出 `align` / `cases` / `matrix` 等环境必须用 `$$` 包裹
- **前端进度显示**：显示对应老师名称，计时上限 180s
- **雷达图重写**：HiDPI 支持、径向渐变填充、自适应标签对齐
- **fix**: 移除重复注册的 `/solve/step2` 路由
