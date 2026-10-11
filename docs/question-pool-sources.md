# 原题池来源与导入

原题池用于主人核对、归类和预览。来源记录与正式题库分开保存，导入原题不会发布母题。完整采集题干及原文件；图形依赖题保留题干、原图定位和出处，进入待核对或暂缓清单。

## 当前库存与新功能

2026-10-11 原题池有 **23,255 道去重题、23,536 条出处**。已经删除 13,001 道能够证实为 2015 年及以前的题；未知年份保留。正式题库仍为 33 道。下面按每道题最先导入的来源计数，因此五行可合计，重复出处不重复计题。

| 来源 | 独立题 | 占比 |
| --- | ---: | ---: |
| 高考真题 LaTeX 汇编（清理后） | 2,789 | 11.99% |
| HighMATH | 4,399 | 18.92% |
| Conic10K | 10,860 | 46.70% |
| 新高考结构化模考数据 | 4,124 | 17.73% |
| 公开免费模考试卷 PDF | 1,083 | 4.66% |

这不是全由高考真题构成的题库。当前解析几何初筛标签 12,984 道（55.83%），函数与导数 2,391 道（10.28%），概率统计 1,340 道（5.76%）。标签允许重叠；“函数与导数”不能全部视为导数压轴题。

新增「原题池 → 题源与导入 → 在线找题」，也可运行 `python3 scripts/collect_question_sources.py --years 2025 2026 --concurrency 20`。自动来源目前是 [gaokao-related-math](https://huggingface.co/datasets/cheese233/gaokao-related-math) 与 [武汉教育资源网](https://www.wh111.com/shuxue/jingxuanshiti/gaozhongshuxue/gaosanshuxueyuekao/) 的公开免费文件。结构化源完整下载 13,915 条原始数据；按年份、地区和实际题型筛出 229 套模考、4,351 条出处，相关 568 张题图全部缓存。PDF 保留整份原卷，候选和专题索引可离线读取。

原答案不是采集条件，不自动解题。获取失败和结构核验未通过的记录保留原因及原文定位。操作方法、缓存与 agent 读取入口见 [指南](question-pool-agent-guide.md)，本轮具体结果见 [交付报告](question-source-collection-report.md)。

## 初次下载的固定版本（清理前历史快照）

2026-10-10 初次下载三个来源的文字数据、README 及存在的许可证。各文件逐一核验 Git blob SHA-1，与对应固定提交的 GitHub 文件树一致。这三个固定版本当时未下载题图、重绘文件或发布版 PDF；后续新增源已缓存题图及原卷。本地数据放在 Git 忽略的 `.runtime/question-pool/sources/`，不提交到项目源码。

| 来源 | 固定提交 | 原始条目 | 文字完整 | 待核对 | 暂缓图形 |
| --- | --- | ---: | ---: | ---: | ---: |
| [高考数学题库 20261004](https://github.com/DxAThing/Gaokao-Math-Problems-Compilation/releases/tag/20261004) | `009953bcd079a219e18166d1e443ce8931b9c731` | 16,321 | 9,827 | 4,099 | 2,395 |
| [HighMATH](https://github.com/tjunlp-lab/HighMATH) | `0f1a363616acc9c2fde6683db960a20db95f45a6` | 4,399 | 4,355 | 0 | 44 |
| [Conic10K](https://github.com/whyNLP/Conic10K) | `9458b879e82e57d37ecc94dea09676d59a160483` | 10,861 | 10,686 | 172 | 3 |

此表是适配器切题前后核对的原始数量，尚未扣除跨来源完全相同题目。每题完整性根据题干、图形标记和原答案判断，不能代替数学内容的人工审核。综合题允许多个大板块；关键词分类只是初筛，不推断细分套路。每个目录的 `acquisition-manifest.json` 保留下载清单、固定提交、文件哈希及统计。

高考主源的 777 份 LaTeX 正文恰好解析出 16,321 个 problem 环境。独立原答案提取出 11,192 项，原解析提取出 15,930 项；部分解答题只有完整原解析，没有独立答案字段，保留原解析并标记待核对。固定源码中的 391 项没有独立解析块，因此保留为空，而不是依据发布说明补造解析。来源自身的条件修订、版本差异和错误提示保留在原始源码中。

## 许可与出处

- 主源的项目原创编排、注释等采用 [CC BY-SA 4.0](https://github.com/DxAThing/Gaokao-Math-Problems-Compilation/blob/009953bcd079a219e18166d1e443ce8931b9c731/LICENSE)，需要项目署名、修改说明、相同方式共享及上游 [deekur/gaokaomath](https://github.com/deekur/gaokaomath) 的适用署名。其许可明确不授予项目不持有的第三方权利。
- HighMATH 的固定版本没有 LICENSE，公开再分发权限待核验。
- Conic10K 有 [MIT LICENSE](https://github.com/whyNLP/Conic10K/blob/9458b879e82e57d37ecc94dea09676d59a160483/LICENSE)，文本针对软件；题目和第三方题源的公开再分发范围仍需核对。

三个来源默认 `publication_allowed=false`。导入 CLI 只有显式 `--publication-allowed` 才会更改这一默认值。保留来源不表示已取得所有第三方材料的公开发布授权。

## 导入命令

先检查数量与状态：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/import_question_pool.py \
  --source-name '高考数学真题汇编 20261004' --kind compilation \
  --path .runtime/question-pool/sources/compilation-20261004 \
  --revision 009953bcd079a219e18166d1e443ce8931b9c731 \
  --url https://github.com/DxAThing/Gaokao-Math-Problems-Compilation/releases/tag/20261004 \
  --license 'CC BY-SA 4.0；保留上游署名；第三方权利待核验' --dry-run
```

移除 `--dry-run` 才写入本地主人原题池。使用相同来源信息和版本重复导入，不新增相同来源定位。HighMATH 使用 `--kind highmath` 及对应目录；Conic10K 使用 `--kind conic10k` 及对应目录。公开仓库数据导入不调用 OCR 或解题 AI。

自定义 JSONL 支持每行一个对象，字段为 `source_key`、`question`、`answer`、`solution`、`categories`、`question_type`、`year`、`region`、`question_no`、`page_start`、`page_end`、`completeness`、`reason`。畸形行、空题干及未知格式条目保留为失败项，原始记录保存在出处中，不静默忽略。

## 教辅文件

PDF 的文字层按页提取，TXT 用换页符保留页码；编号题可拼接跨页续文，并尝试关联独立的编号答案区。无法可靠切题的片段也保留。DOCX 读取正文、表格和常见 Word 公式，分页只反映文件中显式分页符，实际打印页码需核对。文件提取结果全部待人工核对，原文件及原页定位供回看。

图片、扫描 PDF 可勾选 OCR，批量转换支持 auto/off/force。已有 DeepSeek Flash 图片接口最多 20 并发，PDF 读取与渲染串行，网络请求并发；成功页面按文件哈希、页码、模型与配置缓存。普通文件导入可保留原答案，在线找题只转录题干，均不补题或解题。OCR 输出始终待核对。先按试卷分段再切题，续文只在同卷内拼接，页脚与答题须知不参与题号切分。格式或 OCR 失败页保留原文件，可单独重试。

“如图”“三视图”等明确依赖图形的信息以及图片选项会进入暂缓清单；文字条件完整的几何题照常初筛。只有图形标记但依赖性不明确的题进入待核对，不能猜出缺失条件。
