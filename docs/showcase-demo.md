# 科研展示站

部署目标为 `https://demo.150.chat/home.html`，正式业务站为 `https://150.chat/`。本轮先完成本地验收、提交并推送 GitHub，再由用户在阿里云 Workbench 手动同步；本文描述新版本，不表示服务器已经更新。

## 内容与来源

页面为 14 章连续长页：总览、基础表示、单题能力、诊断对照、错题题库、套路训练、试卷、生涯、教学协同 Agent、教师、学校、两种教学模式、MCP 适配、自进化。开场用全国卷三角形、仿手写作答和系统分层结构图建立整体认识，再逐章展开。顶部主线持续标出当前环节。每章先说明现实痛点，再进入机制、演示与研究对照；公开界面统一使用“学生作答”的称呼，原始录制和来源记录保留原文。

正文直接展示研究比较，设计说明放在侧边批注；详细解答、难度图和完整模型原文使用右侧批注面板。14 项相关工作附研究网站及论文／官方文档地址，并用输入、方法、产出的逻辑图说明研究路线。公开页面不列内部源文档清单，不使用折叠展开块。无 JavaScript 时仍可阅读正文、设计批注和论文比较。

章节设计依据来自 15 份完整阅读的 Markdown。`showcase-content-map.json` 保存原文 SHA-256、行数、参考章节及研究链接；`build_research_showcase.py` 在构建前检查这些记录，原文变化后必须重新阅读并更新映射。`research-content.json` 保存经过核对的页面文案，生成的 HTML 仍提交到 Git，便于直接发布。论文任务、方法、结果和版本定位见 [研究核对记录](showcase-research-notes.md)。

主案例为 **2023 年新课标全国Ⅰ卷第17题（解三角形）**；补充案例为 **2025 年全国一卷第16题（数列）**。公开题库只包含这两题。旧地方卷题干、错答、教学分支、快照和固定试卷已从展示流程退出，旧 PDF 生成器改为提示打印当前选题。

## 真实结果与方案演示

- `pipeline.json` 保留两道题各四位老师的 8 份 Solver → Verifier → Formatter 真实保存结果，包括最终解析及三阶段原始输出。
- `recordings.json` 保留六类预定测试输入及 18 份实际回答：普通模型接收题目与作答、普通模型获得相同可用信息、系统正式批改流程。基础模型、思考配置和温度相同。普通提示词要求引用依据、接受正确替代解法并保留不确定判断。
- 五帧教学记录覆盖引导、错误回答、请求提示、部分作答及补充完整作答后的推进。变式保留同一个原始候选、录制器故障及恢复后的三阶段检查，当前候选通过检查。
- 新录制通过本地正式业务代码和真实模型 API 完成，`execution_origin=local_production_code`；不是线上正式站 HTML 抓取。临时工作区承接业务函数的必要写入，不写主人题库。
- 六类学生作答为本项目构造的测试情境，不是真实学生数据；比较区域展示双方完整实际结果，观察目标与模型回答分开。常规模型也有正确诊断的结果，不以少量例子报告准确率提升或学习效果。
- 时间戳分析、完整生涯、教师与学校流程、外部 MCP 适配等用“方案演示”或“研究方向”标识，不预制成功的模型回答。

展示层只做安全文本排版、数学渲染及布局适配。统一多余 JSON 转义层的显示适配不修改保存内容；原始模型响应仍放在 `.record-text` 节点中逐字保留，可在批注面板核对。步骤卡片直接读取正式批改函数返回字段，不用人工观察目标替换实际诊断。

仿手写作答使用本地 `StudyAgent Handwriting` 字体（32,540 字节，240 个字形），由 OFL 许可的 LXGW WenKai TC 裁剪并重新命名；不依赖读者电脑的系统字体。纸面中的 `_`、`^` 采用上下标排版，原输入保留在对应 `data-source` 和公开录制记录中。字体来源、许可证和覆盖校验位于 `frontend/showcase/fonts/`。

## 只读边界

`backend.showcase:app` 仅开放明确白名单中的页面、公开 JSON、数学和图形资源；不导入主人后端、数据库、教学或 AI 模块。浏览器只发同源 GET 请求，无账号、Cookie、自动模型调用或业务写入。部署维护端点限本机直连。题库分片由公开 manifest 校验，未列出的旧图片、PDF 和其他文件不可访问。

题库、题单与打印在本地浏览器状态内操作，公开页不把模拟的选题、时间轴或掌握情况写成真实学生档案。所有模型调用都只在显式录制命令中发生。

## 构建与本地预览

```bash
.venv/bin/python scripts/build_showcase_data.py
.venv/bin/python scripts/build_research_showcase.py
.venv/bin/python scripts/build_research_showcase.py --check
.venv/bin/python scripts/run_demo.py --port 8302
```

浏览器打开 `http://127.0.0.1:8302/home.html`。数学、字体和图形资源均本地提供，预览无需模型配置。

`run_showcase_pipeline.py` 和 `record_showcase_cases.py --run` 会实际调用配置的模型，日常构建不调用它们。录制来源、输入和故障恢复见 [录制说明](showcase-recordings.md)。

## 验收

```bash
.venv/bin/python -m unittest tests.test_research_showcase tests.test_research_release tests.test_showcase tests.test_showcase_data tests.test_showcase_pipeline tests.test_showcase_bank tests.test_showcase_recordings -q
REQUIRE_RECORDINGS=1 node tests/e2e/research_showcase_smoke.mjs
```

浏览器验收使用已安装 Playwright 的 Node 环境；必要时用 `NODE_PATH` 指向该环境。覆盖 14 章、2 题 × 4 老师、几何辅助线、六情境双条件、原始响应逐字一致、教学推进、真实变式、题库筛选与组卷打印、键盘操作、减少动效、1440/390/320 宽度、无脚本阅读，以及只读网络边界。

提交前再运行 `git diff --check`，核对公开文件没有凭据、个人学习记录或私人数据库。演示站发布只替换公开展示资源与最小展示后端，保留前一版本以便回滚。GitHub 与 Workbench 步骤见 [发布说明](research-showcase-release.md)。

## 动画与章节衔接

开屏复用原有“数学 · love”连笔素材的展示站副本，书写加速后约 1.1 秒自动结束；没有跳过开场按钮或进度条。原站共享素材不修改。页面使用原生 CSS 与 SVG 动画，14 处章节桥梁分别展示本章产出、传递过程和下一环输入。结构图、论文逻辑图及学生作答只播放短动效，保留原生滚动、键盘操作和减少动态效果模式。
