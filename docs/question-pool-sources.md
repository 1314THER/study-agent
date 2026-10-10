# 原题池来源与导入

原题池用于主人核对、归类和预览。来源记录与正式题库分开保存，导入原题不会发布母题。此阶段只处理文字条件完整的题；图形依赖题保留题干和出处，进入暂缓清单。

## 已下载的固定版本

2026-10-10 已下载三个来源的文字数据、README 及存在的许可证。各文件逐一核验 Git blob SHA-1，与对应固定提交的 GitHub 文件树一致。未下载题图、重绘文件或发布版 PDF；本地数据放在 Git 忽略的 `.runtime/question-pool/sources/`，不提交到项目源码。

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

图片、扫描 PDF 默认等待 OCR。主人明确导入并勾选 OCR 后，调用已有 DeepSeek 图片接口逐页转录，保留原答案和原解析，不让模型补题或解题；OCR 输出始终待核对。明确标记为上页续文且题号相符的相邻页会拼接，仍保留每个页片段定位。OCR 或格式解析失败可按原文件重试。

“如图”“三视图”等明确依赖图形的信息以及图片选项会进入暂缓清单；文字条件完整的几何题照常初筛。只有图形标记但依赖性不明确的题进入待核对，不能猜出缺失条件。
