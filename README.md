# 成为数学高手 — AI 学习伴侣

> 当前版本：v0.8.1.1（2026-08-03）

面向高中生的 AI 数学学习系统。基于 DeepSeek V4 多老师路由与 Solver → Verifier → Formatter 三段流水线，同时提供多模态切题、手把手教学、AI 仿题、个人题库、题单、错题与组卷系统。完整开发路线见 [ROADMAP.md](ROADMAP.md)。

---

## 核心流程

```text
文本 / 文件（PDF、图片、docx、txt）
  → 多模态切题（Qwen-VL-Max，可选）
  → Solver：解答 + 板块分类 + 雪碧了检测
  → Verifier：分块 + 标准过程 + 详细过程 + 步骤难度 + 知识点
  → Formatter：一致性校验 + LaTeX 检查 + 聚合
  → 前端展示（步骤卡片 + 雷达图 + 整体难度）
  → 保存到个人题库（自动 / 手动）
  → 题单 / 错题 / 组卷购物车 / 手把手教学
```

---

## 四老师系统

| 老师 | Solver 模型 | Verifier 模型 | Formatter 模型 | UI 主题 | 描述 |
|------|------------|--------------|---------------|---------|------|
| 🫅 梁梁 | deepseek-v4-flash | deepseek-v4-flash (low) | deepseek-v4-flash (low) | 黄色 | 快速，但是可能出错 |
| 🎩 韬韬 | deepseek-v4-pro (low) | deepseek-v4-flash (medium) | deepseek-v4-flash (low) | 粉色 | 更慢但更聪明 |
| 🏃 雪峰 | deepseek-v4-pro (high) | deepseek-v4-flash (medium) | deepseek-v4-flash (low) | 紫色 | 每一步考虑得更多 |
| 🐔 鸡 | deepseek-v4-pro (high) | deepseek-v4-flash (high) | deepseek-v4-flash (high) | 绿色 | 每一步都要考虑半天 |

老师选择通过 `teacher` 参数传给解题与教学接口，进度消息显示对应老师名称，前端主题色跟随老师切换。

---

## 前端页面

| 页面 | 文件 | 说明 |
|------|------|------|
| 单题解答 | `frontend/index.html` | 文本搜题 + 分步展示 + 保存到个人题库 |
| 多模态解答 | `frontend/multimodal.html` | 上传文件切题 + 批量解题 + 多会话管理 |
| 老师手把手教你做题 | `frontend/teach.html` | 对话式分步教学 + 跳过/看答案 + 错因标记 |
| 个人题库 | `frontend/history.html` | 题目列表 + 详情（含雷达图）+ 题单 + 购物车 |
| 组卷 | `frontend/exam.html` | 从购物车组卷 + 排序 + 双模式 + 导出 PDF |

所有页面共享 `frontend/style.css`、`frontend/radar.js`、`frontend/nav.js`，左侧导航支持展开/收起和移动端抽屉。

### 主要特性

- **单题解题**：三步流水线带进度、耗时、token 展示；搜前开关默认自动入库，搜后也可手动保存
- **去重**：同一题目内容不会重复入库，重复保存返回已有 ID
- **多模态切题**：支持 PDF / JPG / PNG / docx / txt，解析为 LaTeX 题目列表，可编辑、可预览、可批量解题
- **批量并发**：多模态页批量解题并发上限 7 道，互不阻塞
- **手把手教学**：AI 按步骤引导，学生作答后检查对错、提示错因；支持跳过、直接看答案、提示关键词
- **错因标定**：七类错因（符号错误/计算错误/公式记错/知识性错误/审题错误/思路错误/其他），可在单题页、题库详情、多模态会话中标记和删除
- **题单**：系统题单「全部 / 母题 / 高考题」+ 动态「错题」+ 用户自建题单；题目可加入多个题单
- **来源标签**：`ai生成 / 高考题 / 模拟题 / 精选母题`，可带卷名、题号、参考题 ID、母题 ID 等二级信息
- **AI 仿题**：从题目详情、错题列表或教学总结页触发，基于原题与错因生成 3 道变式题，并发跑三步解题校验后自动入库
- **筛选搜索**：关键词（空格 AND）+ 板块 + 题型 + 难度 + 来源 + 错因 + 分页
- **页面记忆**：localStorage 持久化老师选择、输入、保存开关、导航状态、教学会话、多模态会话、组卷购物车
- **时区**：时间显示 UTC+8
- **KaTeX 渲染**：列表预览、详情、教学会话中的 LaTeX 公式自动渲染
- **组卷**：购物车选题目 → 排序 → 学生版/教师版预览 → 导出 PDF

---

## 路线图

当前处于 v0.8.1.1（AI 仿题已上线）。接下来的产品路线以两套学习系统为主线：母题计划（覆盖高考 130+ 分套路题）与个人错题本；以 AI 改题/改卷和 OCR 作答识别为两大能力，最终由全局智能体总控。

| 版本 | 主题 | 重点 |
|------|------|------|
| v0.9 | 母题矩阵与种子库 | 内容地基 |
| v0.10 | AI 改题 | 【重点】防欺骗第一道闸，可立即开工 |
| v0.11 | OCR 作答识别 | 并行线，可与 v0.10 同时推进 |
| v0.12 | 母题掌握闭环 | 核心闭环 |
| v0.13 | 记忆曲线复习 | 常规 |
| v0.14 | 个人错题本 | 常规 |
| v0.15 | 学情总览 | 常规 |
| v0.16 | 试卷维度与 AI 改卷 | 【重点】防欺骗第二道闸 |
| v0.17 | 全局智能体 | 【最高重点】总控收口 |
| v2.0 | 教师端与学校端：母题作业、学情调整、AI 出卷、笔触时间戳 OCR 改卷、开放配置 | 多角色协同 |
| v3.0 | 教研端：母题/YAML 治理、教学效果与教师 KPI、高考教材变更响应 | 内容治理 |

详细设计、数据层扩展与验收标准见 [ROADMAP.md](ROADMAP.md)。

---

## 步骤数据结构

每个步骤包含：

| 字段 | 内容 | 展示 |
|------|------|------|
| `title` | 一句概括（一级步骤名） | 和步骤号同行 |
| `step_level1` | 二级步骤名（与 `steps.yaml` 对应） | 步骤副标题 |
| `standard_writing` | 保留关键公式的推导路径 | 默认显示 |
| `detailed_writing` | 原始解答裁切，保护 `$...$`、`$$...$$` 和 `\begin{...}...\end{...}` 边界 | 点击展开 |
| `knowledge_point` | 该步骤涉及的知识点 | 标签展示 |
| `step_difficulty` | 单步五维难度（dimensions + score + level） | 难度徽标 |

教学会话还会在步骤上补充 `step_prompt`（引导问题）和 `step_answer`（参考答案），最终答案以 `step_number = 999` 的步骤形式保存。

---

## 难度评分

全管线只保留一套难度标准：**每个步骤由 Formatter 打五维分（每维 0-3）**，块难度和整题难度全部由后端从步骤五维确定性聚合，AI 不再单独打总分。

| 维度 | 0 分 | 1 分 | 2 分 | 3 分 |
|------|------|------|------|------|
| 非常规程度 | 完全套路 | 熟悉套路小变形 | 套路组合或少见变形 | 无现成套路，需构造思路 |
| 计算量 | 心算 | 2-3 步笔算 | 4-6 步或繁琐化简 | 7 步以上大计算量 |
| 分类讨论 | 无需 | 隐含讨论或简单二分 | 三分类 | 四分类以上或嵌套讨论 |
| 知识广度 | 单一知识点 | 同板块多个知识点 | 两个板块联动 | 三个及以上板块综合 |
| 条件转化难度 | 条件直接可用 | 一次简单翻译/代入 | 换元、等价变形、多层转化 | 条件隐蔽，需构造性转化 |

聚合算法：

```text
维度分 = min(3, 该维步骤最大值 + floor(0.5 × 该维非零步骤均值 × 非零步骤占比))
总分   = min(15, 1 × 得 1 分的维度数 + 2 × 得 2 分的维度数 + 4 × 得 3 分的维度数)
```

等级映射：`0-3 容易 | 4-6 中等 | 7-9 困难 | >=10 极难`；无法评分的数据标记为「未知」。这样 1 分只加很少的分，2 分明显加重，3 分影响最大，且 2/3 分越多总分越高。

Formatter 校验失败时自动重跑一次 Verifier 再试；仍失败则返回报错，同时保留新 Verifier 结果，难度标记为未知。

---

## 组卷系统

### 换页规则

- **3px 规则（全局）**：内容逐块追加到 DOM，用 `getBoundingClientRect()` 实时测量实际高度，距底边不足 3px 时自动翻页
- **更频繁的换页选项（学生版）**：每题渲染结束后剩余空间不足 150px 时换页
- **无估算**：完全依赖浏览器实际布局引擎测量，无字符数估算

### 答题框跨页

学生版答题框即将跨页时自动拆分为两段，两端底部标注「超出答题区域的答案无效」（6pt 黑体加粗）。

### PDF 导出

导出前清空 `.a4-page` 的 `border`、`box-shadow`、`margin`，避免导出时出现灰线；支持学生版（仅题目 + 答题区）和教师版（含完整解答过程）。

---

## 项目结构

```text
study-agent/
├── backend/
│   ├── main.py              # FastAPI 服务器（路由 + 静态文件服务）
│   ├── solver.py            # TEACHER_CONFIG + 三阶流水线 + 解析/清洗/校验
│   ├── teach.py             # 手把手教学：步骤生成、逐题检查、对话式会话
│   ├── multimodal.py        # 多模态切题：PDF/图片/docx/txt → Qwen-VL-Max
│   ├── database.py          # SQLite：题库、错因、题单、来源、时间追踪
│   ├── categories.py        # categories.yaml 的 Python 接口
│   ├── categories.yaml      # 知识点单一数据源（板块→二级→三级）
│   ├── steps.py             # steps.yaml 的 Python 接口
│   ├── steps.yaml           # 题型步骤表（一级步骤→二级步骤）
│   └── prompts/
│       ├── solver.md        # Solver 提示词
│       ├── formatter.md     # Formatter 提示词
│       ├── latex_rules.md   # 全局 LaTeX 格式要求
│       ├── extraction.md    # 多模态切题提示词
│       ├── teach_check.md   # 步骤对错检查提示词
│       ├── teach_format.md  # 步骤转引导问题提示词
│       ├── teach_chat.md    # 对话式教学提示词
│       └── verifiers/       # 分板块/分题型 Verifier 提示词
├── frontend/
│   ├── style.css            # 公共样式
│   ├── radar.js             # 公共雷达图
│   ├── nav.js               # 公共导航（展开/收起/移动端抽屉）
│   ├── index.html           # 单题解答
│   ├── multimodal.html      # 多模态解答
│   ├── teach.html           # 手把手教学
│   ├── history.html         # 个人题库 + 题单
│   └── exam.html            # 组卷 + PDF 导出
├── study_agent.db           # SQLite（自动创建）
├── requirements.txt
├── .env                     # DEEPSEEK_API_KEY / DASHSCOPE_API_KEY（已 .gitignore）
├── .gitignore
├── start.sh                 # 启动后端
├── stop.sh                  # 停止后端
├── ROADMAP.md               # 开发路线图（详细）
└── README.md
```

---

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/solve/step1` | Solver：解答 + 板块提取 + 雪碧了检测 |
| POST | `/solve/step2` | Verifier：分块 + 标准/详细过程 + 步骤难度 + 知识点 |
| POST | `/solve/step3` | Formatter：全局校验 + 聚合 + 可选入库 |
| POST | `/questions/save` | 保存题目（去重，已有则返回 ID），可带来源标签 |
| GET | `/questions` | 题目列表（摘要 + 分类 + 难度 + 来源） |
| GET | `/questions/search` | 搜索：关键词 + 板块 + 题型 + 难度 + 来源 + 错因 + 分页 |
| GET | `/questions/errors` | 有错因记录的题目列表 |
| GET | `/questions/{id}` | 单题完整记录（含 `answer_json`、`step_errors`） |
| DELETE | `/questions/{id}` | 删除单题 |
| POST | `/questions/{id}/exam-touch` | 标记最近一次组卷时间 |
| POST | `/questions/{id}/step-error` | 记录步骤错因 |
| DELETE | `/questions/{id}/step-error/{eid}` | 删除步骤错因 |
| POST | `/questions/{id}/generate` | AI 仿题：生成变式题、校验、筛选并入库 |
| POST | `/questions/{id}/generate/async` | 异步启动 AI 仿题，返回任务 ID |
| GET | `/generate-jobs/{job_id}` | 查询 AI 仿题任务进度与结果 |
| GET | `/categories` | 知识点分类（categories.yaml 动态加载） |
| GET | `/steps` | 所有题型的两级步骤结构 |
| POST | `/questions/ai-search` | AI 语义搜索（预留，当前返回空列表） |
| POST | `/exam/ai-assemble` | AI 一键组卷（预留，当前返回开发中提示） |
| POST | `/multimodal/parse` | 上传文件并切题为题目列表 |
| POST | `/teach/find` | 查找题库中已有教学步骤 |
| POST | `/teach/start` | 开启教学并返回所有步骤 |
| POST | `/teach/check` | 检查学生单步作答 |
| POST | `/teach/session/start` | 创建对话式教学会话 |
| POST | `/teach/session/{session_id}/chat` | 发送学生消息 |
| GET | `/teach/session/{session_id}` | 获取会话完整信息 |
| GET | `/question-lists` | 获取所有题单（含动态错题） |
| POST | `/question-lists` | 创建用户题单 |
| PUT | `/question-lists/{list_id}` | 重命名用户题单 |
| DELETE | `/question-lists/{list_id}` | 删除用户题单 |
| GET | `/question-lists/{target}/questions` | 题单题目（`all`/`wrong`/数字 ID + 筛选分页） |
| POST | `/questions/{qid}/lists` | 将题目加入多个题单 |
| DELETE | `/questions/{qid}/lists/{list_id}` | 从题单移除题目（软删除） |
| GET | `/questions/{qid}/lists` | 获取题目所在题单 ID |
| PUT | `/questions/{qid}/source-type` | 更新来源类型与二级标签 |
| GET | `/` | 前端入口（重定向到 index.html） |

解题与教学接口可传 `teacher`：`liangliang` / `taotao` / `xuefeng` / `ji`，默认梁梁。

前端静态文件由后端 `StaticFiles` 挂载在 `/` 下，所有页面通过 `http://127.0.0.1:8000` 访问，同源共享 localStorage。

---

## 数据结构

### categories.yaml

知识点唯一数据源，结构为「板块 → 二级分类 → 三级知识点」。当前共 12 个板块、86 个二级分类、541 个三级知识点：

```text
集合与逻辑用语、不等式、一元二次式、函数与导数、指对幂耐克函数、
三角函数、平面向量、复数、立体几何、数列、解析几何、概率统计
```

### steps.yaml

题型步骤表，结构为「题型 → 一级步骤 → 二级步骤」。当前题型：

```text
选择题、填空题、立体几何大题、解析几何大题、解三角形大题、
数列大题、简单的概率统计大题、困难的概率大题、函数与导数大题、
其他非常规压轴大题、简单的非标准题目
```

Verifier 输出的步骤名会与 `steps.yaml` 比对，非法步骤名被重置；`knowledge_points` 会从三级知识点映射/过滤为合法二级知识点。

### questions 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 自增主键 |
| `content` | TEXT | 题目原文（唯一） |
| `answer_json` | TEXT | 完整结构化答案 |
| `category_level1` | TEXT | 一级分类 |
| `category_level2` | TEXT | 二级分类 |
| `difficulty_level` | TEXT | 容易/中等/困难/极难 |
| `difficulty_score` | INTEGER | 0-15 |
| `difficulty_dimensions` | TEXT | 五维难度 JSON |
| `knowledge_points` | TEXT | 知识点列表 JSON |
| `question_type` | TEXT | 选择题/填空题/大题 |
| `steps_structure` | TEXT | 步骤索引 JSON |
| `source_type` | TEXT | ai生成/高考题/模拟题/精选母题 |
| `source_meta` | TEXT | 来源二级标签 JSON |
| `common_mistakes` | TEXT | 预留 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |
| `last_viewed_at` | TIMESTAMP | 最近查看时间 |
| `last_edited_at` | TIMESTAMP | 最近编辑（错因/题单）时间 |
| `last_exam_at` | TIMESTAMP | 最近组卷时间 |

### 其他表

| 表 | 说明 |
|------|------|
| `question_lists` | 题单：系统题单（全部/母题/高考题）+ 用户题单；「错题」为动态查询 |
| `question_list_members` | 题单-题目关联，软删除用 `is_removed` |
| `step_errors` | 步骤错因：step_number、chunk_id、mistake_type、mistake_detail |
| `mistakes` | 预留错题表 |
| `practice_records` | 预留练习记录表 |

### 来源标签

| `source_type` | `source_meta` 允许字段 |
|------|------|
| `模拟题` / `高考题` | `paper`、`question_no` |
| `ai生成` | `reference_id` |
| `精选母题` | `owner`、`mother_id` |

入库时来源、分类、难度维度、知识点都会做合法性清洗。

---

## 启动

```bash
cd study-agent
pip install -r requirements.txt
# .env 中配置：
# DEEPSEEK_API_KEY=sk-xxx
# DASHSCOPE_API_KEY=sk-xxx（多模态切题用）
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

> 注：docx 解析需要 `python-docx`，若当前环境未安装可执行 `pip install python-docx`。

浏览器打开：

| 页面 | 地址 |
|------|------|
| 单题解答 | `http://127.0.0.1:8000/index.html` |
| 多模态解答 | `http://127.0.0.1:8000/multimodal.html` |
| 手把手教学 | `http://127.0.0.1:8000/teach.html` |
| 个人题库 | `http://127.0.0.1:8000/history.html` |
| 组卷 | `http://127.0.0.1:8000/exam.html` |

---

## 版本记录

| 版本 | 内容 | 状态 |
|------|------|------|
| V0.1 | Solver / Verifier / Formatter 三阶流水线 | ✅ 完成 |
| V0.2 | 单用户小题库 + 入库清洗 | ✅ 完成 |
| V0.3 | 前端三页 + 导航 + 错因标记 + 可视化错题 | ✅ 完成 |
| V0.4 | 组卷 + PDF 导出 + 多模态支持 | ✅ 完成 |
| V0.5 | 知识点/步骤表 YAML 单一数据源 + 分板块 Verifier | ✅ 完成 |
| V0.6 | 手把手教学 + 对话式教学会话 | ✅ 完成 |
| V0.7 | 多题库：题单、来源标签、错题、时间追踪 | ✅ 完成 |
| V0.7.1-3 | 共享导航、移动端适配、保存弹窗、来源标签完善 | ✅ 完成 |
| V0.8 | AI 仿题：变式生成 + 完整流水线校验 + 自动入库 | ✅ 完成 |
| V0.8.1 | AI 仿题异步任务、进度轮询、匹配度筛选 | ✅ 完成 |
| V0.9+ | 母题矩阵、AI 改题、OCR 作答识别、掌握闭环、记忆复习、错题本、学情、试卷改卷、全局智能体 | 📋 见 [ROADMAP.md](ROADMAP.md) |
| V2.0 | 教师端与学校端：母题作业、学情调整、AI 出卷、笔触时间戳 OCR 改卷、开放配置 | 📋 探讨中 |
| V3.0 | 教研端：母题/YAML 治理、教学效果与教师 KPI、高考教材变更响应 | 📋 探讨中 |
