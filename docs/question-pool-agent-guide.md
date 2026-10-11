# 在线找题与 agent 获取入口

在原题池打开「题源与导入 → 在线找题」，填年份（默认最近两年，本轮为 2025、2026），点击「开始找题」。任务在后台运行，关闭页面后仍会继续；重新打开原题池可恢复后台任务进度。结果进入原题池，原答案和解析不作为采集条件，也不调用解题 AI。

当前自动题源是 Hugging Face 的结构化新高考数据，以及武汉教育资源网公开目录中可直接下载的免费文件。完整题源登记、核验状态和阻塞原因在 `config/question-sources.json`。公众号、网盘和登录站点是补漏线索，只有实际取得文件后才计为已获得资料。

## 一条命令运行

从项目根目录执行，沿用项目已有 DeepSeek 配置，无需复制或输出密钥：

```sh
python3 scripts/collect_question_sources.py --years 2025 2026 --concurrency 20
```

默认搜索全部已配置目录，下载免费题源、识别扫描题干，并将核验通过的题放入原题池。默认排除北京、天津、上海，模考核验实际题号与题型为 8 单选、3 多选、3 填空、5 解答。未知年份保留；能够证实为 2015 年及以前的题在共同导入入口跳过。

只找和下载文件，不调用 OCR：

```sh
python3 scripts/collect_question_sources.py --download-only
```

随后只处理已下载文件：

```sh
python3 scripts/collect_question_sources.py --cached-only --no-structured --concurrency 20
```

`--no-import` 只输出候选，不写库；`--no-ocr` 只提取文字层；`--max-pages 32` 是每个公开目录的分页上限。`--quiet` 只打印最终摘要，`--report /path/result.json` 可另存完整报告。未来年份用 `--years` 指定，不能拿网页发布日期推断题源年份。搜索每次重新查看公开目录，文件按来源 URL 和 SHA256 缓存；OCR 按文件哈希、页码、模型、提示词及转换配置缓存。重跑不覆盖人工修订，不重新识别成功页，不重复新增同一来源定位。网页和脚本共享运行锁，避免两个采集任务同时写同一缓存。

完全复用现有文件和识别结果（包括保留失败页，不再次请求）：

```sh
python3 scripts/collect_question_sources.py --cached-only --no-retry-failed --quiet
```

默认会重试失败页；只有成功页保证不重复请求。`--cached-only` 也会使用已验证的本地结构化快照，不查询上游最新版本。在线更新失败时会明确报告并尝试复用旧快照。

## 结果在哪里

所有数据保存在 Git 忽略的 `.runtime/question-pool/`，源码、配置及文档留在 Git 中。迁移项目时需单独复制 `.runtime/question-pool/` 和数据库；即使上游链接失效，已下载版本仍能读取。

| 文件／目录 | 用途 |
| --- | --- |
| `collections/progress.json` | 当前阶段、数量与进度 |
| `collections/collection-report.json` | 题源链接、获取失败原因、结构核验与 OCR 请求数量 |
| `collections/reports/<运行编号>.json` | 每次运行的独立报告 |
| `collections/discovery-report.json` | 最近搜索结果，缓存转换时仍保留未取得的题源链接 |
| `collections/resources/<来源哈希>/resource.json` | 卷名、原始 URL、文件格式、SHA256 |
| 同目录 `original.pdf`、`source.html`、`questions.jsonl` | 原文件、来源页面和逐题数据 |
| `collections/collected-questions.jsonl` | 本轮切出的所有题目候选，核验未通过的也保留 |
| `collections/derivative-candidates.jsonl` | 函数与导数候选，需区分真正导数题 |
| `collections/probability.jsonl` | 概率统计候选 |
| `collections/comprehensive-probability.jsonl` | 概率统计解答题候选，需进一步核对是否达到综合压轴难度 |
| `sources/gaokao-related-math/latest.json` | 最近成功获取的结构化快照入口 |
| `sources/gaokao-related-math/snapshots/<提交>/` | 原始 JSONL、题图、逐题 JSONL、专题索引、采集清单 |

读取 JSONL 时逐行遍历文件后调用 `json.loads`，不要用 `read_text().splitlines()`；部分原文含 Unicode 行分隔符，后者可能把一条 JSON 拆开。公式保留 LaTeX，不要自行去掉反斜杠。稳定定位键为 `source_key`；`question` 是题干加选项；`year`、`region`、`question_no` 是题源信息。`raw.original_file`、`page_start`、`page_end` 可回看 PDF；`raw.paper_url` 指向公开出处。图形题保持待核对，原文件或 `raw.image_assets` 保留全部已下载图形。PDF 题图引用与 JSON 图片引用均参与去重。

结构化快照可离线验证和重新生成：

```sh
python3 scripts/sync_question_sources.py --offline
```

查上游最新版本并下载题图：

```sh
python3 scripts/sync_question_sources.py --revision latest
```

使用登记的固定版本：`--revision pinned`。官方 Hugging Face 无法访问时尝试登记的镜像，并核验提交及已知文件哈希。失败更新不会替换最后成功的入口；附件失败时成功文件已缓存，重跑只补失败项。原始数据有 13,915 条，不代表全国模考全集，也不能保证上游作者今后的更新频率。

## 自有资料转换

```sh
python3 scripts/convert_question_sources.py /path/to/books \
  --output .runtime/question-pool/candidates.jsonl \
  --ocr auto --concurrency 20 --retry-failed
```

支持 PDF、DOCX、TXT、JSON／JSONL、TeX 和图片；`--pages 1,3-8` 可选页。先按试卷分段再按题号切题，跨页续题只在同卷内拼接。公式、图表或边界无法确认的内容保留定位，进入待核对区。OCR 使用 DeepSeek Flash；读取和渲染 MuPDF 时串行，网络请求并发，所有 DeepSeek 调用共享进程内 20 个并发槽。

在线采集只转录题目。为减少答案页的识别，整卷先处理前四页，缺题时再扩展；专题文档保留完整文件并逐页读取。不是所有源文件都能自动通过结构核验，未通过的 JSONL 和原文件保留给后续 agent，不自动补写缺失题干。

## 原题池清理与验证

清理脚本默认只生成计划；`--apply` 先备份原题池、正式题库和套路数据库，再删除可靠证实的旧题及关联。

```sh
python3 scripts/prune_old_questions.py
```

2026-10-10 已执行清理，删除 13,001 道旧题；2016 年和未知年份保留，正式题库当时保留 33 道。删除清单、数据库备份及结果在 `.runtime/question-pool/cleanup/20261010-222555-148783/`。实测重新导入高考汇编跳过 13,479 条旧出处，新增加 0 条，旧题没有恢复。

相关验证命令：

```sh
python3 -m unittest tests.test_pool_sources tests.test_question_pool \
  tests.test_source_policy tests.test_source_conversion tests.test_jobs \
  tests.test_question_source_collector
node tests/frontend_question_pool.test.mjs
```

实测 2026 汕头模考相同两页，串行 10.475 秒、两页并发 6.355 秒，均 2 次请求；缓存重跑约 0.004 秒、0 次请求。此数据比较同提示词与解析程序的调度方式，不是完整旧实现对照，也不能推算 20 并发的实际提速。20 并发上限另外通过模拟请求验证。

本轮实际库存、来源占比、采集结果、未取得资料与验证记录见 [交付报告](question-source-collection-report.md)。公众号入口目前仅登记线索；没有验证出可稳定自动下载的完整公众号题库。自动采集专题目录和从完整试卷提取专题候选，也不能证明已经收齐全国模考或同难度的全部压轴题。
