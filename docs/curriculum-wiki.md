# 数学课时库

本地版主导航“数学课时库”或 /curriculum-wiki.html，仅主人访问。接入原 FastAPI 应用，不需要新的前端构建环境。旧服务需要重新启动才能加载新增 API。

## 内容与验收边界

基准为人教 A 版 2019 教材体系的必修两册、选择性必修三册，面向现行新高考全国一卷，不将旧全国Ⅰ卷文理科体系混入主线。教材选学内容保留标记，不声称都是高考必考。

初始数据包含 329 个建议课时、174 个知识节点和 288 个现有参考套路。73 个正文节次与 90 个阅读、探究、建模、小结和复习节点均保留目录定位、教学安排和来源。五册印刷目录已对照保存的原书逐项核对。**目录定位核实不等于课时数学内容完成教师审核。**

课时正文为原创教学摘要，安排约45分钟新授、习题、探究和复习；阅读内容可融入对应课时，不为了增加数量将每篇阅读都强制拆为45分钟。高三复习另建路线，复用首次学习的知识节点。初始状态均为待审核。

四类教辅入口为《教材帮》《一遍过》《解题觉醒》《五年高考三年模拟》。官方入口、真实读到的题页、数学解析完整性、人工匹配审核是不同证据。没有取得题页的资料不计逐题读取，ISBN与印次未核实处留空。不能把已有高考题改标成教辅题。

## 来源与研究记录

- [教材原书公开镜像](https://github.com/litongjava/china_high_school_math_people_teach_a_version_pdf)：2019目录内五册，出版社原作；镜像不是出版社分发站点。
- [天星官方试读](https://www.tesoon.com/customize/ebook)
- [解题觉醒官方介绍](https://www.tesoon.com/articles/detail?id=180886)
- [曲一线同步系列](https://www.quyixian.com/Book/WSGZTB/)
- [曲一线产品手册](https://mobile.quyixian.com/ProductManual/)

原件及入口HTML位于 .runtime/curriculum-wiki/evidence/。扫描教材目录使用本机Vision OCR辅助转录，再核对原页；OCR文本不直接当作已核实题干。PDF页码与印刷页码分开：必修两册偏移7页，选必三册偏移5页。

官方试读进一步定位到三种天星教辅的阅读器；阅读器书架与正文不是同一读取状态。备用官方书架已实际读取《一遍过》26版人教A必修一40页试读包的封面、若干目录页及印刷第1页，录入其中6题。原书答案册未读取，解法中单独显示本次研究推导答案；其他页面仍保持缺口。

初始化、复用现有匹配及重新生成报告：

~~~sh
.venv/bin/python scripts/build_curriculum_wiki.py
.venv/bin/python scripts/build_curriculum_wiki.py --import-existing-matches --limit 288
.venv/bin/python scripts/curate_curriculum_examples.py
.venv/bin/python scripts/import_curriculum_workbook_sample.py
~~~

第二条命令只复用现有原题池的套路分类：要求条件完整、有原解析、置信度高、原文引用确实存在，并核对题目版本。课程关联仍是草稿，**完整解法前置未知时保持未知**，不会以章节标签推断所有小问适合当前课时。不改写原题池和正式母题；重复执行不重复建立相同解法。

来源采集工具：

~~~sh
.venv/bin/python scripts/research_curriculum_sources.py
.venv/bin/python scripts/research_curriculum_sources.py --textbooks --previews
.venv/bin/python scripts/research_curriculum_sources.py --readers
~~~

网络访问可能需要执行环境授权。脚本保存原件和摘要，不执行来源脚本。scripts/ocr_curriculum_front.swift 只用本机 Apple Vision，不是数学校验器。

## SQLite 数据字典

默认数据库 .runtime/curriculum-wiki.sqlite3，使用 data_path 隔离账号或测试工作区。正式业务以此SQLite为准，原件保存为私人证据。

| 表 | 内容 |
|---|---|
| cw_meta | schema、种子与全局人工修订版本 |
| cw_entities | book、chapter、section、outline、lesson、knowledge、routine、source、solution；稳定ID、排序、正文JSON、状态与修订号 |
| cw_edges | 类型、证据来源、定位、理由、生成方式与审核状态 |
| cw_history | 修改者、理由、时间及事务前后差异，仅记录变化记录 |
| cw_runs | 批次、模型配置快照、完成项、状态及后台任务 |
| cw_suggestions | 绑定实体版本的待审建议，独立于正式内容 |
| cw_cache | 以内容、来源、目录、模型和提示词版本缓存成功结果 |

原题按 pool_item_id、occurrence_id、item_version 和正文摘要引用。解法另记小问、方法、步骤、前置知识和来源快照。多出处与多解法分别保留；原题变化或出处消失时提示过期，保留旧结论。

当前实库为234条解法记录：227条复用的原题池草稿、1条同题的早期代数解法、6条真实教辅试读题的研究解法。8项既有原解析已补充逐步前置分析。尚未核实完整前置的记录继续提示未知，不算作已校正匹配。

参考套路标识为 routine:SET-010 等，namespace 为 routine_catalog。formal_pattern_id 独立，不能将参考编号转换成 mastery.db 整数主键。

| 关系 | 含义 |
|---|---|
| prerequisite | 当前课时→前置课时，必须无环 |
| requires / teaches | 需要知识 / 本课引入知识 |
| practices | 课时安排某题的小问解法 |
| routine_candidate | 课时或解法的目录方法候选 |
| covers | 教材目录节点安排到课时 |
| related | 关联或拓展，不是硬前置 |

排序与依赖分开。改变排序后重新报告前置晚于当前、知识尚未引入、解法超前及前置未核实。同课新授后的练习可以使用本课引入知识。

题目展示按例题、基础、巩固、变式、综合排列；同阶段支持人工设置顺位，随后按出处与题号自然排序。同题的不同解法分别保存阶段和顺位，避免把后学方法提前。纯文字题未缓存原页不会被误报为缺少题图；真正依赖图形的题目仍显示缺图提示。

## 人工校正与LLM

课时页支持正文、目标、知识点和条件校正；关系编辑器调整前置、知识和套路联系。拆合归档旧课时并重接关系，编号不因重排改变。章末与阅读覆盖关系保留。

人工修改必须附理由与 expected_revision；冲突返回409，浏览器保留输入。历史展示前后差异，可恢复未发生后续冲突的修改；存在后续修改时阻止无提示覆盖。

模型任务须在课时或题目处显式启动：

1. 原文片段有来源和定位，只有书名不能生成有据草稿。
2. 复用现有模型配置与全局并发限制，不另保存密钥。
3. 草稿引文必须是指定来源与定位中的连续原文。
4. 套路匹配复用原解析核验及全目录复查规则。
5. 结果先入建议队列，主人应用后才改内容，不后台覆盖人工结论。
6. 暂停在当前请求结束后生效，逐项保存成功项，重启后可人工续跑和重试。
7. 浏览、检索、导出不会触发AI。

JSON导出 /curriculum-wiki/export 保留类型、稳定编号和网页链接；增加 format=markdown 参数得到只读Wiki投影。编辑导出件不会回写SQLite。

## API 摘要

统一前缀 /curriculum-wiki，接口及HTML均复用主人权限。

| 行为 | 接口 |
|---|---|
| 查询 | GET /overview、/lessons、/entities、/lessons/{id} |
| 校正 | PATCH /entities/{id}，GET/POST /relations |
| 课时操作 | PUT /order，POST /lessons/{id}/split、/merge |
| 新增知识 | POST /knowledge，须指定首次引入课时 |
| 资料与题目 | POST /sources/import、/questions，GET /sources/{id}/file |
| 依赖及版本 | GET /checks、/questions/{id}/freshness |
| 历史 | GET /history、/history/{revision}，POST /history/{revision}/restore |
| 任务 | POST/GET /runs，POST /runs/{id}/control |
| 建议 | GET /suggestions，POST /suggestions/{id}/apply、/reject |
| 导出 | GET /export?format=json 或 markdown |

资料导入使用 source 元数据对象和 excerpts 原文定位数组，另附修改版本与理由。PDF、DOCX和图片题目提取沿用原题池上传，再关联到课时，不另写OCR流程。

## 验证与备份

~~~sh
.venv/bin/python -m unittest tests.test_curriculum_wiki -v
.venv/bin/python -m unittest tests.test_routine_graph tests.test_runtime_snapshot tests.test_jobs tests.test_question_pool tests.test_routine_review -q
~~~

测试隔离至临时SQLite并模拟模型，覆盖目录安排、权限、依赖环回滚、超前解法、缺失前置、来源伪标拦截、题目过期、拆合恢复、并发冲突、引文核验、人工保护和断点。

运行快照已包含新数据库与证据目录；原题池、图片及参考套路仍需一起备份。数学内容和匹配的最终正确性需要人工逐课逐题审核，程序验证不计作教师确认。

## 本次验收记录（2026-10-24）

- 教材目录安排163/163，329个建议课时，174个知识点；这是课程覆盖，不是数学内容已通过教师审核。
- 288个参考套路中，274个有待审课程关联，14个有明确待关联原因。原有分类只是候选证据。
- 234条解法中233条有套路候选；一条有限集合直接判断题未强行匹配现有套路。人工确认0/563（课时与解法合计）。
- 依赖图无环；219条解法前置未知，3条超前解法需要调整使用课时或改用早期解法。保留提示，不自动隐藏。
- 《一遍过》40页试读已读5个页面单元，实际录入6题；其他三类资料只有官方入口，读取率分母未知。未把试读读取比例当作整书读取率。
- 139项Python测试通过，另通过前端语法与原任务页面脚本回归；模型流程采用模拟响应验证，未以付费模型生成结果冒充人工审核。
- 浏览器实际验证了页面加载、公式、来源筛选、课时切换、校正表单和真实题目展示。移动端采用响应式分区布局，尚未完成真实手机浏览器人工验收。

机器可读的覆盖、来源和逐条依赖提示见 outputs/curriculum-wiki-report.json。待补数据可从本地工作台继续校正，无需改动前端代码。
