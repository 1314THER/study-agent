# 成为数学高手 — AI 学习伴侣

面向高中生的 AI 数学学习系统。基于 DeepSeek V4，三段流水线 + 四老师配置 + 五维难度评分 + 个人题库 + 组卷系统。

---

## 核心流程

```
用户输入题目
  → Solver（解答 + 板块分类 + 雪碧了检测）
  → Verifier（分块 + 标准过程 + 详细过程 + 难度评分）
  → Formatter（一致性校验 + LaTeX 检查 + 聚合）
  → 前端展示（步骤卡片 + 雷达图 + 整体难度）
  → 可选项：保存到个人题库（搜前开关 / 搜后按钮）
  → 个人题库可回看完整解析
  → 组卷：从题库选题 → 排序/自定义 → 导出学生版/教师版 PDF
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
| 和老师对答案 | `frontend/index.html` | 搜题 + 分步展示 + 保存到个人题库 |
| 老师手把手教你做题 | `frontend/teach.html` | 手把手教学（预留） |
| 个人题库 | `frontend/history.html` | 题目列表 + 详情（含雷达图）+ 加入组卷购物车 |
| 组卷 | `frontend/exam.html` | 从题库选题组卷 + 排序 + 设置 + 导出 PDF |

所有页面共享 `frontend/style.css`，左侧导航栏 72px。

### 特性

- **保存到个人题库**：搜前开关默认勾选，自动入库；搜完后也可手动点击"加入个人题库"按钮
- **去重**：同一个题目不会重复保存
- **页面记忆**：localStorage 持久化老师选择、输入框内容、保存开关状态、上次结果
- **时区**：显示 UTC+8 时间
- **KaTeX 渲染**：列表预览和详情中的 LaTeX 公式自动渲染
- **购物车机制**：个人题库中勾选题目加入组卷购物车
- **拖拽排序**：组卷页面内可通过拖拽或方向按钮调整题目顺序
- **分栏可调**：组卷页面的左侧/右侧分界线可拖拽调整宽度（200-800px）
- **双模式预览**：组卷支持学生版（仅题目+答题区）和教师版（含完整解答过程）
- **PDF 导出**：一键导出学生版或教师版 PDF

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

## 组卷系统（exam.html）

### 换页规则

- **3px 规则（全局）**：内容逐块追加到 DOM，用 `getBoundingClientRect()` 实时测量实际高度，距底边不足 3px 时自动翻页
- **150px 规则（学生版 + 频繁换页）**：每题渲染结束后，若剩余空间 < 150px 则换页
- **无估算**：完全依赖浏览器实际布局引擎测量，无字符数估算

### 答题框跨页

当学生版答题框即将跨页时，自动拆分为两段，两端底部标注"超出答题区域的答案无效"（6pt 黑体加粗）

### PDF 导出

导出前清空 `.a4-page` 的 `border`、`box-shadow`、`margin`，避免导出时灰线

---

## 项目结构

```
study-agent/
├── backend/
│   ├── main.py              # FastAPI 服务器（路由 + 接口）+ 静态文件服务
│   ├── solver.py            # 核心：TEACHER_CONFIG + 三步调用 + 解析 + 清洗
│   ├── database.py          # SQLite 小题库 + 入库清洗 + 增删查
│   ├── categories.py        # 知识点分类字典（唯一数据源）
│   ├── prompts/
│   │   ├── solver.md        # Solver 提示词（含 ###板块### 硬编码格式）
│   │   ├── formatter.md     # Formatter 提示词（含 LaTeX 检查）
│   │   └── verifiers/       # 9 个板块级 Verifier prompt
│   └── __init__.py
├── frontend/
│   ├── style.css            # 公共样式
│   ├── index.html           # 搜题做题页
│   ├── teach.html           # 手把手教学·预留
│   ├── history.html         # 个人题库（列表 + 详情 + 购物车）
│   └── exam.html            # 组卷（预览 + 排序 + 设置 + 导出）
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
| POST | `/questions/save` | 手动保存题目到个人题库（带去重） |
| GET | `/questions` | 题目列表（摘要 + 分类 + 难度） |
| GET | `/questions/search` | 搜索题目（关键词 + 板块 + 难度 + 题型筛选） |
| GET | `/questions/{id}` | 单题完整记录（含 `answer_json`） |
| DELETE | `/questions/{id}` | 删除单题 |
| GET | `/categories` | 知识点分类列表 |
| POST | `/questions/ai-search` | AI 语义搜索（预留） |
| POST | `/exam/ai-assemble` | AI 一键组卷（预留） |
| GET | `/` | 前端入口（重定向到 index.html） |

所有接口都接受可选 `teacher` 参数：`liangliang` / `taotao` / `xuefeng` / `ji`，默认梁梁。

前端静态文件由后端通过 `StaticFiles` 挂载在 `/` 路径下提供，所有页面通过 `http://127.0.0.1:8000` 访问，同源共享 localStorage。

---

## 数据结构

### categories.py

```python
CATEGORIES = {
    "解析几何": ["直线与圆", "椭圆", "双曲线", "抛物线", ...],
    "立体几何": ["空间位置关系", "平行与垂直证明", ...],
    "数列": ["等差数列", "等比数列", "数列求和", ...],
    "函数与导数": ["函数概念与性质", "指数函数", ..., "导数综合"],
    "三角函数与解三角形": ["三角恒等变换", ...],
    "概率与统计": ["排列组合", "二项式定理", ...],
    "非常规压轴题": ["新定义理解", "新运算规则", ...],
}
```

### 数据库 questions 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 自增主键 |
| `content` | TEXT | 题目原文（唯一，UNIQUE） |
| `answer_json` | TEXT | 完整结构化答案（JSON blob） |
| `category_level1` | TEXT | 一级分类 |
| `category_level2` | TEXT | 二级分类 |
| `difficulty_level` | TEXT | 容易/中等/困难/极难 |
| `difficulty_score` | INTEGER | 0-15 |
| `difficulty_dimensions` | TEXT | 五维度得分 JSON |
| `knowledge_points` | TEXT | 知识点列表 JSON |
| `question_type` | TEXT | 选择题/填空题/大题/非常规压轴题 |
| `common_mistakes` | TEXT | 预留 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

### 入库清洗

所有结构化字段入库前经过合法性校验：

| 字段 | 清洗规则 |
|------|---------|
| `category_level1` | 必须在 CATEGORIES 的 key 里 |
| `category_level2` | 必须在 CATEGORIES[level1] 的子列表里 |
| `difficulty_level` | 必须是 容易/中等/困难/极难 之一 |
| `difficulty_dimensions` | key 必须是 5 个维度之一 |
| `knowledge_points` | 必须在 CATEGORIES[level1] 的子列表里 |

---

## 启动

```bash
cd study-agent
pip install -r requirements.txt
# 设置 .env: DEEPSEEK_API_KEY=sk-xxx
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

后端运行在 `http://127.0.0.1:8000`，同时提供 API 和前端静态文件。浏览器打开：

| 页面 | 地址 |
|------|------|
| 和老师对答案 | `http://127.0.0.1:8000/index.html` |
| 手把手教学 | `http://127.0.0.1:8000/teach.html` |
| 个人题库 | `http://127.0.0.1:8000/history.html` |
| 组卷 | `http://127.0.0.1:8000/exam.html` |

---

## 版本规划

| 版本 | 内容 | 状态 |
|------|------|------|
| V0.1 | 做题系统基础版（Solver / Verifier / Formatter） | ✅ 完成 |
| V0.2 | 单用户小题库 + 入库清洗 | ✅ 完成 |
| V0.3 第一阶段 | 前端三页 + 侧边栏 + 入库控制 + 题库 + 页面记忆 | ✅ 完成 |
| V0.3 第二阶段 | 手把手教学（干扰项生成 + 选择题交互 + E 路径） | 🚧 待开发 |
| V0.4 | 组卷系统 + 购物车 + 排序 + PDF 导出 | ✅ 完成 |
| V0.4.1 | 真实 DOM 测量换页 + 拖拽排序 + 分栏可调 | ✅ 完成 |
| V0.5 | 智能刷题 / 出题系统 | 📋 规划中 |
