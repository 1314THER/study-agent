# 展示页研究对照核对记录

核对日期：2026-10-25（Asia/Shanghai）。范围：展示页重点相关工作与协议材料的任务、方法、结果和适用范围。正文维护在 `frontend/showcase/research-content.json` 的 `research` 字段；本文件记录定位依据，不提供新的项目实验结论。

## 一手材料与定位

| 工作 | 核对的原文 | 重点定位 |
| --- | --- | --- |
| Verify-then-Generate | [EMNLP 2024 PDF](https://aclanthology.org/2024.emnlp-main.478.pdf) | §3–4 的输入与验证器；图 1 的反馈失败示例；§6.3、表 3 的人工评价。将正误、首错、错误描述与步骤对齐区别处理。 |
| MathCog | [arXiv v2 HTML](https://arxiv.org/html/2504.00843v2) | §3 的数据筛选与清单；§4 的 OCR 输入；§5.2、表 4 的证据强弱及错误分析。 |
| LongTutor | [ACL 2026 PDF](https://aclanthology.org/2026.acl-long.1371.pdf) | 图 1–2 的跨题情境；§3–5 的历史取证、状态诊断、教学行动与评价。 |
| EQPR | [ACL 2025 PDF](https://aclanthology.org/2025.acl-long.628.pdf) | §4 的 Critic、Reflection、MCTS；§5–6 的数据及三类评测；附录 A.4 的评价提示词。 |
| STEPwise | [arXiv v1 HTML](https://arxiv.org/html/2610.16344v1) | §4–5 的四阶段八子技能和材料生成；§6.2 的课堂使用；§7.2–7.4 的个性化、粒度与限制。 |
| Tutor CoPilot | [arXiv v3 PDF](https://arxiv.org/pdf/2410.03017v3) | 摘要、Introduction、Results；教师主动触发、选择教学建议及实地随机对照。 |
| CogChain | [AIED 2025 作者版 PDF](https://shenleixian.github.io/pdf/iPen.pdf) | §3 的数字笔采集；§4.1–4.3 的时间分组、类型与题号分类、甘特图；§5 的模式分析。 |

## 展示中的比较对象

每篇重点研究增加 `task`、`method`、`findings`、`source_location`、`source_url` 和 `version`；保留 `contribution`、`scope`、`response`、`validation` 以兼容页面构建。

- **任务输入先对应。** 学生错误验证、参考解结构化、书写类型分类、长期状态推断和题目生成是不同任务，不因均使用“步骤”就合并比较。
- **研究证据与系统演示分开。** 原文案例说明其任务与观察；本项目全国卷测试是另行构造的输入与真实模型运行，不能标成原论文数据或教师金标准。
- **结果引用有版本。** Tutor CoPilot 采用 v3 PDF 的结果；摘要页面与 PDF 的样本口径不同，页面不混拼二者。其他数值同样保留对应版本和任务。
- **CogChain 的轨迹是落笔至抬笔过程。** 书写类型与题号分类并非数学步骤错因标签；2 秒是论文用于分组的启发式，不作为学生卡住的通用阈值。模式与表现的关系不写成干预因果效果。
- **评价对象保持分开。** Verify-then-Generate 的反馈评价不等于学习保持；MathCog 的知道与应用领域不等于完整素养；LongTutor 的取证成功不等于行动适配；EQPR 的可解性不等于目标符合；STEPwise 的课堂使用不等于随机提分试验。

## 与本项目逐项对应

单题章节比较“显式错误判断怎样指导后续反馈”；诊断章节比较“证据模糊时如何保留判断和继续验证”；时间线比较“书写片段如何进一步对齐数学操作”；试卷章节比较“单题目标怎样进入题位与整卷复核”；长期章节比较“历史证据怎样改变任务和后续判断”；教师章节比较“分析怎样进入行动与复测”。

页面应同时展示已有工程机制和需要验证的增量环节。前人的研究范围不是其系统永久不能做到的边界，新增工具或流程连接也不是学生学习效果的证明。

## 补充一手材料

| 工作 | 原文 | 定位与版本 |
| --- | --- | --- |
| MathFish：让数学任务关联课程标准 | [原文](https://aclanthology.org/2024.findings-emnlp.323.pdf) | §3–5，图 1、§4.2 生成题审核表（PDF pp.1–7）；Findings of EMNLP 2024 正式论文 |
| Numbas：后续步骤可以显式依赖前一步回答 | [原文](https://numbas.org.uk/behind-the-design/adaptive-marking.html) | 官方 Adaptive marking 的 Problem、Solution、Difficulties；Marking algorithms 的 interpreting/testing/feedback；官方设计文档，核对于 2026-10-25 |
| PFA：用成功与失败练习历史建立表现基线 | [原文](https://pact.cs.cmu.edu/pubs/AIED%202009%20final%20Pavlik%20Cen%20Keodinger%20corrected.pdf) | §1、§2.1；公式 1–3、表 3（PDF pp.3–6）；AIED 2009 作者修正版 |
| MET：教学评价需要多来源证据 | [原文](https://cepr.harvard.edu/file_url/2595) | 2013 综合报告 Key Findings／Combining Measures，随机分配技术报告 Introduction；MET 三年研究综合报告与随机分配报告，2013 |
| 高中数学 AI 实验：做得更好与学得更好分开测 | [原文](https://hamsabastani.github.io/education_llm.pdf) | §2 Experimental Design、§3 Results／Unassisted Performance（作者版 PDF pp.5–11）；PNAS 2025 论文作者版 |
| MCP 与宿主官方文档 | [原文](https://modelcontextprotocol.io/specification/2026-07-28) | MCP Overview／Server Features；DSH Summary／Use this package；WorkBuddy MCP＋Skill 接入；MCP 2026-07-28；宿主文档核对日期 2026-10-25 |
| RAG：检索记忆与模型参数是不同改进路径 | [原文](https://arxiv.org/pdf/2005.11401v4) | 摘要、§2–4（arXiv v4）；NeurIPS 2020，arXiv v4，2021-04-12 |
