# 成为数学高手 — AI 学习伴侣

> 持续开发中；具体版本以仓库最新提交为准。

面向高中生的 AI 数学学习系统。基于 DeepSeek V4 多老师路由与 Solver → Verifier → Formatter 三段流水线，同时提供首页教练台、全局智能体、手写作答识别、一键规划、多模态切题、手把手教学、AI 仿题、个人题库、题单、错题与组卷系统。完整开发路线见 [ROADMAP.md](ROADMAP.md)。

---

## 新成员快速开始

需要 Git、Python 3.9 或更新版本，以及首次安装依赖时的网络连接。克隆仓库后，在项目目录运行对应脚本：

| 系统 | 命令 |
|------|------|
| macOS（终端） | `./start.sh` |
| Windows（命令提示符或 PowerShell） | `start.bat` 或 `./start.bat` |

```bash
git clone https://github.com/1314THER/study-agent.git
cd study-agent
./start.sh                 # macOS；Windows 改用 start.bat
```

首次运行会创建 `.venv`、安装 `requirements.txt`，并从 `demo-data/` 复制题库和学习记录快照到本地；随后启动服务并打开[首页](http://127.0.0.1:8000/home.html)。再次运行不会覆盖本地数据库。终端按 `Ctrl+C` 停止服务。克隆后的题库已有 25 道题，以及套路、闯关和练习记录，便于直接查看各页面。

**AI 功能需要使用自己的 API 密钥。**在[系统设置](http://127.0.0.1:8000/settings.html)填写，或将 `.env.example` 复制为 `.env` 后填写 `DEEPSEEK_API_KEY`；多模态功能另需 `DASHSCOPE_API_KEY`。仅浏览现有题库、记录和页面无需密钥。`.env`、运行时 `backend/settings.json` 和本地数据库不会提交到 Git。

如需参与开发，请看 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## Ubuntu 服务器与邀请预览

上面的 `start.sh` / `start.bat` 会在**自己的电脑上**运行一份本地服务。Ubuntu ECS 的安装、自启动、数据迁移和备案完成后的 HTTPS 配置见 [deploy/ubuntu.md](deploy/ubuntu.md)。服务器上的 FastAPI 只监听 `127.0.0.1:8000`。

备案期间，可以通过 SSH 邀请朋友连接服务器上的同一份题库：

| 使用者 | 项目内文件 | 用法 |
|--------|------------|------|
| 主人（Mac） | [deploy/connect-owner.command](deploy/connect-owner.command) | 需要已获授权的 `~/.ssh/study-agent-ecs` 密钥；双击后输入密钥口令，保持终端窗口打开 |
| 朋友（Mac） | [deploy/share-preview/connect-study-agent.command](deploy/share-preview/connect-study-agent.command) | 首次双击生成专用公钥，发给主人授权；再次双击连接 |
| 朋友（Windows） | [deploy/share-preview/connect-study-agent.cmd](deploy/share-preview/connect-study-agent.cmd) 和同目录的 `.ps1` | 两个文件放在同一文件夹，双击 `.cmd`；首次生成公钥，授权后再次双击 |

朋友的完整操作见 [分享说明](deploy/share-preview/README-zh.txt)。主人在服务器以 root 身份运行 [授权脚本](deploy/authorize-preview-key.sh)，按提示粘贴每位朋友的公钥；只接收公钥，不共享私钥。授权脚本把朋友的 SSH 权限限制为转发到本应用。连接后浏览器会打开 `http://127.0.0.1:18000/home.html`：这个地址在**各自电脑上**，访问的却是服务器上的同一份题库。被邀请的人可以编辑题库和设置，也会使用服务器配置的 AI 接口。

当前上海 ECS 的域名仍在 ICP 备案审核中。备案成功并完成 HTTPS 配置后再开放域名访问；备案前不要把网站通过公网 IP、域名或临时公网网址开放。SSH 预览无需开放应用的 8000 端口。

---

## 核心流程

```text
文本 / 文件（PDF、图片、docx、txt）
  → 多模态切题（Qwen-VL-Max，可选）
  → Solver：解答 + 板块分类 + 雪碧了检测
  → Verifier：分块 + 标准过程 + 详细过程 + 步骤难度 + 知识点
  → Formatter：一致性校验 + LaTeX 检查 + 聚合
  → 前端展示（步骤卡片 + 步骤五维柱状图 + 整题雷达图 + 整体难度）
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

> 表格为默认配置；四老师的模型与思考强度可以在「系统设置」页热修改，保存后立即生效。

---

## 前端页面

| 页面 | 文件 | 说明 |
|------|------|------|
| 首页教练台 | `frontend/home.html` | 学情卡片 + 今日待办 + 全局教练全屏对话 |
| 单题解答 | `frontend/index.html` | 文本搜题 + 分步展示 + 保存到个人题库 |
| 多模态解答 | `frontend/multimodal.html` | 上传文件切题 + 批量解题 + 多会话管理 |
| 老师手把手教你做题 | `frontend/teach.html` | 对话式分步教学 + 跳过/看答案 + 错因标记 |
| 个人题库 | `frontend/history.html` | 题目列表 + 详情（含雷达图）+ 题单 + 购物车 |
| 组卷 | `frontend/exam.html` | 从购物车组卷 + 排序 + 双模式 + 导出 PDF |
| 母题看板 | `frontend/mother.html` | 母题管理 + 板块顺序编辑入口（规划中 UI） |
| 套路循环 | `frontend/loop.html` | 母题/变式循环练习 + 一键规划入口 |
| 巩固日历 | `frontend/calendar.html` | 套路巩固排期 + 一键规划入口 |
| 闯关 | `frontend/board.html` | 只读闯关任务路线 |
| 关卡编辑 | `frontend/level-editor.html` | 自由拖拽思维导图编辑关卡、套路与顺序 |
| AI 改卷 | `frontend/grade.html` | 选择题/填空题直接判答案，大题按标准步骤 AI 判分，记录作答来源与防欺骗信号 |
| 系统设置 | `frontend/settings.html` | 难度评分公式、老师模型、API 密钥与服务商切换、性能与并发限制 |

所有页面共享 `frontend/style.css`、`frontend/radar.js`、`frontend/dimchart.js`、`frontend/nav.js`、`frontend/agent.js`、`frontend/agent.css`，左侧导航支持展开/收起和移动端抽屉；其他页面右下侧提供可折叠的全局教练抽屉，日历与套路循环页额外加载 `frontend/planner.js`。

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
- **AI 改题（文字）**：选择题/多选题/填空题直接判答案；大题按标准步骤 AI 判分，不严谨但无缺步只提醒，思路不同时独立判分并给出新思路；判分后自动给出步骤错因建议，错题可确认标签并一键匹配/新建套路，套路状态同步到巩固日历；每次作答与防欺骗信号写入 `practice_records`
- **筛选搜索**：关键词（空格 AND）+ 板块 + 题型 + 难度 + 来源 + 错因 + 分页
- **页面记忆**：localStorage 持久化老师选择、输入、保存开关、导航状态、教学会话、多模态会话、组卷购物车
- **时区**：时间显示 UTC+8
- **KaTeX 渲染**：列表预览、详情、教学会话中的 LaTeX 公式自动渲染
- **组卷**：购物车选题目 → 排序 → 学生版/教师版预览 → 导出 PDF
- **步骤五维柱状图**：每一步的难度标签旁显示五维横向柱状图，颜色随分值 0/1/2/3 变化
- **系统设置**：运行时调整难度评分权重、总分封顶与等级阈值，四个老师的三阶段模型与思考强度，DeepSeek / Qwen / 豆包 API 密钥与地址；CC Switch 风格弹窗一键切换服务商，保存即热生效
- **首页教练台**：学情卡片、今日待办（来自巩固日历）、快捷入口与全屏教练对话
- **全局智能体**：规则快路径 + 多步工具循环（搜索 / 解题 / 教学 / 批改 / 规划 / 学情），工具结果回传后继续决策；保留最近 10 轮会话历史；接口以 NDJSON 流式返回进度与逐字回复；agent 消息与结果卡片支持 KaTeX 公式渲染
- **手写作答识别**：`/ocr/answer` 接口，教学页与改卷页可上传手写图片，识别结果回填作答框后继续原流程
- **一键规划**：日历页与套路循环页可打开规划弹窗，按“每天 1/2/3 个”等模板把未掌握套路写入巩固日历；排序支持板块优先级与板块内关卡顺序

---

## 路线图

当前研发与科研计划按时间推进；详细工作、交付物和验收标准见 [ROADMAP.md](ROADMAP.md)。

| 时间 | 重点 |
|------|------|
| 2026 年 10—11 月 | 完成目标套路目录与首批审核母题，统一标注和提示词，改进单题批改并接入教学，建立试卷质量分析与学生全卷时间戳评价原型 |
| 2026 年 12 月—2027 年 1 月 | 制定 Benchmark 标注手册，按题目族划分开发集与封存测试集，完成基线评测、手写笔与客户端原型 |
| 2027 年 2—4 月 | 完善关卡和日历规划，整理 API/MCP 示例，开发专用 Agent 与 RAG，开展获许可的小规模试用或脱敏离线回放 |
| 2027 年 5—6 月 | 真人试用、实验分析、结题报告与演示系统，争取形成本科生科研论文 |

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

评分权重（默认 `[0, 1, 2, 4]`）、总分封顶（默认 15）与三个等级上限（默认 `3 / 6 / 9`）都可在「系统设置」页运行时调整，保存后无需重启即热生效。Formatter 提示词对 2/3 分设了硬门槛：选择题/填空题原则上不允许 2 分及以上，大题也只有真正达到压轴程度（构造思路、7 步以上大计算、四分类或嵌套讨论、三个以上板块综合、隐蔽条件需构造性转化）才允许出现。

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
│   ├── agent.py             # 全局智能体：指令 → 结构化动作（规则 + DeepSeek 决策）
│   ├── planner.py           # 一键规划：板块顺序 + 板内顺序 → 巩固日历
│   ├── settings.py          # 运行时设置：评分公式 / 老师模型 / API 密钥（settings.json 热加载）
│   ├── solver.py            # TEACHER_CONFIG + 三阶流水线 + 解析/清洗/校验
│   ├── teach.py             # 手把手教学：步骤生成、逐题检查、对话式会话
│   ├── grade.py             # AI 改题：文字作答判分（答案比对 + 步骤判分）
│   ├── multimodal.py        # 多模态切题：PDF/图片/docx/txt → Qwen-VL-Max
│   ├── database.py          # SQLite：题库、错因、题单、来源、时间追踪
│   ├── categories.py        # categories.yaml 的 Python 接口
│   ├── categories.yaml      # 知识点单一数据源（板块→二级→三级）
│   ├── steps.py             # steps.yaml 的 Python 接口
│   ├── steps.yaml           # 题型步骤表（一级步骤→二级步骤）
│   ├── settings.json        # 运行时设置（保存后生成，已 .gitignore，优先级高于 .env）
│   └── prompts/
│       ├── solver.md        # Solver 提示词
│       ├── formatter.md     # Formatter 提示词
│       ├── latex_rules.md   # 全局 LaTeX 格式要求
│       ├── extraction.md    # 多模态切题提示词
│       ├── teach_check.md   # 步骤对错检查提示词
│       ├── teach_format.md  # 步骤转引导问题提示词
│       ├── teach_chat.md    # 对话式教学提示词
│       ├── grade.md         # 大题改题判分提示词
│       └── verifiers/       # 分板块/分题型 Verifier 提示词
├── frontend/
│   ├── style.css            # 公共样式
│   ├── radar.js             # 公共雷达图
│   ├── dimchart.js          # 公共步骤五维柱状图
│   ├── nav.js               # 公共导航（展开/收起/移动端抽屉）
│   ├── agent.js             # 全局教练：全屏对话 / 右侧可折叠抽屉 + 动作执行器
│   ├── agent.css            # 全局教练样式
│   ├── planner.js           # 一键规划弹窗（模板 / 日期 / 板块 / 预览 / 写入）
│   ├── home.html            # 首页教练台
│   ├── index.html           # 单题解答
│   ├── multimodal.html      # 多模态解答
│   ├── teach.html           # 手把手教学
│   ├── history.html         # 个人题库 + 题单
│   ├── exam.html            # 组卷 + PDF 导出
│   ├── mother.html          # 母题看板
│   ├── loop.html            # 套路循环
│   ├── calendar.html        # 巩固日历
│   ├── board.html           # 闯关（只读任务路线）
│   ├── level-editor.html    # 关卡编辑（自由思维导图）
│   └── settings.html        # 系统设置：评分公式 / 老师模型 / API 密钥 / 服务商切换
├── demo-data/               # 完整使用快照：题库与学习记录
├── deploy/                  # Ubuntu 服务配置、数据迁移、SSH 预览与朋友授权脚本
│   └── share-preview/       # Mac / Windows 朋友连接脚本与说明
├── scripts/run.py           # 两平台共用的环境准备和启动逻辑
├── study_agent.db           # 本地 SQLite（首次运行时复制，不提交）
├── mastery.db               # 本地套路与闯关数据（不提交）
├── requirements.txt
├── .env.example             # API 密钥配置示例
├── .gitignore
├── start.sh                 # macOS 启动入口
├── start.bat                # Windows 启动入口
├── CONTRIBUTING.md          # 协作开发说明
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
| POST | `/grade` | AI 改题：文字作答判分（`input_type` 预留手写统一入口） |
| POST | `/grade/text` | 同上，文字判分专用别名 |
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
| GET | `/settings` | 读取系统设置（API Key 掩码返回，含来源 settings/env） |
| PUT | `/settings` | 保存系统设置：评分公式、老师模型、API 地址与密钥 |
| POST | `/settings/reset` | 恢复默认设置 |
| POST | `/settings/test` | 测试 DeepSeek / DashScope 连接 |
| POST | `/agent/act` | 全局教练：自然语言指令 → 结构化动作 |
| GET | `/agent/context` | 首页与教练共享的学情快照 |
| POST | `/ocr/answer` | 手写作答图片识别，返回文本与置信度 |
| POST | `/planner/plan` | 一键规划：生成未掌握套路的日历安排预览 |
| POST | `/planner/apply` | 一键规划：生成并写入巩固日历 |
| GET | `/planner/board-order` | 读取板块顺序配置（含板内关卡顺序） |
| PUT | `/planner/board-order` | 保存板块顺序配置 |
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

前端静态文件由后端 `StaticFiles` 挂载在 `/` 下。页面与 API 使用同源地址：本机直接运行时为 `http://127.0.0.1:8000`，SSH 预览时为各自电脑上的 `http://127.0.0.1:18000`，部署 HTTPS 后为配置的域名。浏览器的 localStorage 按网址分别保存；服务器数据库由所有获授权的访问者共享。

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

## 启动与排查

使用上方的 `start.sh` 或 `start.bat`。依赖文件发生变化时，启动器会自动补装；只想准备环境和数据，可运行 `./start.sh --prepare-only` 或 `start.bat --prepare-only`。

- **找不到 Python**：安装 Python 3.9+；Windows 安装时勾选“Add Python to PATH”，然后重新打开终端。
- **8000 端口被占用**：先关闭先前启动的服务，再运行启动脚本；服务只监听本机 `127.0.0.1`。
- **依赖下载失败**：检查网络后重新运行脚本；安装成功前不会记录依赖已就绪。
- **需要重新体验初始数据**：先备份自己的 `study_agent.db`、`mastery.db`，移走需要重置的数据库，再运行启动脚本。启动器不会覆盖现有文件。
- **AI 功能提示缺少密钥**：在设置页或 `.env` 配置自己的密钥。不要将密钥提交到仓库。

### 日志

后端运行日志统一写入项目根目录的 `logs/`，按天滚动，自动保留最近 14 天：

```bash
tail -f logs/app.log   # 实时查看当前日志
```

- `logs/app.log` 始终是当天的日志，跨天会自动生成 `app.log.2026-08-09` 这类历史文件，旧的超过 14 天后自动清理。
- 终端输出和日志文件会同时保留；接口访问、数据库初始化、AI 调用失败等关键信息都会记录。
- `logs/` 已加入 `.gitignore`，不会提交到代码仓库。

浏览器打开：

| 页面 | 地址 |
|------|------|
| 单题解答 | `http://127.0.0.1:8000/index.html` |
| 多模态解答 | `http://127.0.0.1:8000/multimodal.html` |
| 手把手教学 | `http://127.0.0.1:8000/teach.html` |
| 个人题库 | `http://127.0.0.1:8000/history.html` |
| AI 改卷 | `http://127.0.0.1:8000/grade.html` |
| 系统设置 | `http://127.0.0.1:8000/settings.html` |
| 组卷 | `http://127.0.0.1:8000/exam.html` |

---

## 测试

项目内置了 303 个后端测试和 1 个前端端到端冒烟脚本，覆盖全部 API 路由、
全局 agent 全函数、数据库、解题/教学/改卷/规划/套路/设置/多模态/仿题等模块。
测试使用临时数据库和 mock，不污染 `study_agent.db`、`mastery.db`、
`settings.json` 或 `patterns.yaml`。

```bash
# 后端全量测试（无需额外依赖）
./.venv/bin/python -m unittest discover -s tests -v   # macOS
# Windows: .venv\Scripts\python.exe -m unittest discover -s tests -v

# 前端端到端（需要后端已启动，且本机可用 Playwright/Chrome）
BASE_URL=http://127.0.0.1:8000 node tests/e2e/agent_flow.mjs
```

详细说明见 [tests/README.md](tests/README.md)。

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
| V0.9.4-5 | 首页教练台、全局智能体雏形、手写作答识别、右侧教练抽屉 | ✅ 完成 |
| V0.9.6 | 一键规划器：模板 + 板块/关卡顺序 + 写入巩固日历 | ✅ 完成 |
| V0.9.7 | 全局智能体工具循环、会话历史、NDJSON 流式、公式渲染、全量测试 | ✅ 完成 |
| 2026—2027 研发计划 | 母题内容、统一标注、单题与整卷评价、Benchmark、手写笔客户端、API/MCP、专用 Agent、RAG 与试用 | 📋 见 [ROADMAP.md](ROADMAP.md) |
| V2.0 | 教师端与学校端：母题作业、学情调整、AI 出卷、开放配置 | 📋 后续扩展 |
| V3.0 | 教研端：母题/YAML 治理、教学效果与教师 KPI、高考教材变更响应 | 📋 探讨中 |
