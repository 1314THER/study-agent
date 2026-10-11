# 离线套路整理工作流

先准备目录与脚本，等题库精简结束再导出稳定快照分类。此工具只处理明确指定的 JSONL 文件，输出是审核建议；不会创建正式套路、母题或变式关联。匹配引擎已作为[系统共用功能和 API](routine-matching-api.md)接入，网站整理工作台与真实入库留到后续阶段。

## 先看套路目录

[完整目录与识别边界](routine-catalog.md)列出 288 个细套路；机器读取的目录是 `backend/routine_catalog.json`。它独立于现有 `patterns.yaml` 和题库数据库，编号不随题目排序变化。

| 板块 | 数量 |
|---|---:|
| 集合与逻辑用语 | 28 |
| 不等式 | 16 |
| 一元二次式 | 16 |
| 函数与导数 | 38 |
| 指对幂耐克函数 | 16 |
| 三角函数 | 26 |
| 平面向量 | 17 |
| 复数 | 9 |
| 立体几何 | 26 |
| 数列 | 24 |
| 解析几何 | 36 |
| 概率统计 | 36 |

每条记录有 `id`、`name`、`category`、`signals`（识别特征）、`retrieval_terms`（检索词）、`key_steps`、`exclusions`、`confusable_ids` 和 `aliases`（现有名称参考）。检索词用于找候选，归组须依照原解析的关键步骤和排除条件。名称参考不是已有套路编号，不能据此自动建立关联。

含参集合分别设置 `SET-016` 空集条件、`SET-017` 先分空集再比较端点、`SET-018` 已知非空区间端点检验、`SET-019` 退化单点检验。类似边界也写进切线、二次项退化、有放回与无放回抽样等套路。

目录是第一版参考，并不保证覆盖所有综合题。常规高中方法之外或没有合适目录项的题，生成补充草案供审核。新增编号用未使用的编号，改名保留编号；规则变更时更新目录版本。内容哈希同时参与缓存，漏改版本也会使旧分类缓存失效。

## 准备离线输入

后续在题库精简完成后再导出快照，本轮无需导出。每行一个 JSON 对象，必填 `id`、`version`、`question`，ID 和版本均为正整数，同一文件 ID 不得重复：

```json
{"id":101,"version":1,"question":"设 A=(a,3)，B=(0,4)，求 A⊆B 时 a 的范围。","answer":"a≥0","solution":"先讨论 A 为空集，再在非空时比较区间端点。","categories":["集合与逻辑用语"],"completeness":"complete"}
```

`answer`、`solution` 默认空字符串，`categories` 默认空列表，`completeness` 默认 `unknown`。章节名称取现有 12 个板块。原解析保留原文，不把 API 密钥或账号信息放进输入；其他导出字段不会进入模型请求或分类缓存。

只有完整性明确为 `complete`、有原解析且无需复核的题才参与代表题推荐。缺解析可以得到候选建议；缺图、残缺、完整性未确认、综合题、低或中置信度均进入人工复核。置信度是模型自评标签，不代表测得的正确率。原解析作为依据，不被当成已经核验的答案。

## 运行脚本

在项目根目录执行。默认是预演，不调用 AI，也不创建报告或缓存。

```bash
# 现在即可做：只校验目录
python3 scripts/classify_question_patterns.py --validate-catalog

# 现在即可做：用模拟题检查输入和待处理数量
python3 scripts/classify_question_patterns.py \
  --input tests/fixtures/routine_questions.jsonl \
  --output .runtime/routine-classification-preview

# 等稳定快照准备好后：先预演自己的离线文件
python3 scripts/classify_question_patterns.py \
  --input /absolute/path/questions.jsonl \
  --output .runtime/routine-classification/my-run
```

显式加 `--classify` 才调用 DeepSeek。脚本从 `DEEPSEEK_API_KEY` 环境变量读取密钥，使用独立 HTTP 适配器；不会启动应用、读取账号库或自动打开题库。默认模型 `deepseek-flash`，可用 `--model`、`--base-url` 指定配置；接口需为 HTTPS。密钥不写进报告与缓存。

```bash
# 以后再运行：默认最多新处理100题，每题失败最多尝试2次
python3 scripts/classify_question_patterns.py \
  --input /absolute/path/questions.jsonl \
  --output .runtime/routine-classification/my-run \
  --classify --limit 100

# 相同命令再次运行：复用成功缓存，继续下一批
# --limit 0 处理全部剩余题；--retry-failed 重试缓存失败项
python3 scripts/classify_question_patterns.py \
  --input /absolute/path/questions.jsonl \
  --output .runtime/routine-classification/my-run \
  --classify --limit 100 --retry-failed

# 只利用缓存与人工调整重建报告，无AI调用
python3 scripts/classify_question_patterns.py \
  --input /absolute/path/questions.jsonl \
  --output .runtime/routine-classification/my-run \
  --report-only
```

按原解析与题干的检索证据提取候选，同时保留已给章节的全部套路和易混淆项；章节标签是提示，不限制跨章检索。没有检索依据时给出全目录。条件完整且有原解析，但首次未匹配、中低置信度或提出草案时，会追加全目录复查，避免检索漏项直接变成新套路。模型只能从本次提供的编号中选取；归组结果必须附题干或原解析的连续原文，编造引用和无效编号会被拒绝并重试。输出主套路和最多三个辅助套路；综合题保留整题。

成功或失败结果逐题缓存；`Ctrl+C` 保留已经完成的缓存并生成当前进度报告，下一次跳过完成项。全目录复查前保存初次匹配结果，复查中断后仅续跑复查，状态为 `matching`；复查失败用 `--retry-failed` 重试。其他正在处理的题可能重做。模型请求超时默认 120 秒，可用 `--timeout` 调整；`--attempts` 可设 1–3，对两个阶段分别生效。默认普通匹配一次请求，复查增加一次，每阶段失败最多尝试两次。成功缓存不占 `--limit` 的新处理题额度。题目内容、版本、目录、提示词版本或模型配置变化时重新分类。没有密钥的预演、目录校验和报告重建仍可使用。

## 看报告、选题和修正

独立输出目录包含：

- `assignments.jsonl`：每题的主辅助套路、原文依据、归组理由、复核原因、版本及内容哈希。
- `groups.json`：组内题目、一个母题候选、最多三个变式候选、候补与待复核 ID。
- `review.md`：按组概览与逐题审核清单，包括目录补充草案。
- `unmatched.json`、`unmatched.md`：单列新套路候选、资料不足、归属不确定与请求未完成的题；新候选附原文及最相近已有套路的排除理由。
- `manifest.json`：输入及目录指纹、状态数量、调用尝试数和中断状态。
- `cache/`：逐题缓存，只有当前版本和配置匹配的结果才会复用。

母题按方法典型、条件完整、原解析清楚的建议分数排序。变式优先体现新的边界、设问或结构变化，不为了填满三个槽位而推荐纯数字重复题。其余放候补；待复核题不会作为母题或变式推荐。建议评分和变式特征仍需你确认。

人工调整放在单独的 `overrides.json`（也可通过 `--overrides` 指定）。从明细复制 `id`、`version`、`content_hash`，指定新的主辅助套路，并写说明：

```json
[
  {
    "id": 101,
    "version": 1,
    "content_hash": "从该题明细复制64位内容哈希",
    "primary_routine_id": "SET-018",
    "secondary_routine_ids": [],
    "note": "我已确认题目明确要求集合非空，按非空端点套路处理。"
  }
]
```

上面的哈希文字是占位符，需替换为真实哈希。`primary_routine_id: null` 表示人工暂缓。有效修正优先于模型缓存，不重新调用 AI；报告重建和分类不会改写人工文件。题目版本或内容变更时修正显示为过期，保留原修正但不自动套用，也不把该题推荐为代表题。改主套路时清除旧模型证据、评分和变式特征，避免沿用不适合新组的建议；可在后续工作台补充挑题评分。

## 人工确认新套路

先看 `unmatched.md`。只有 `new_routine_candidate` 可以确认新建：它须经过全目录复查，有完整草案、原文证据和相近套路的排除理由。缺图或缺解析须先补齐，综合题须先确认主方法。AI 草案不直接写目录。

针对一个审核项创建独立 `human-decision.json`，从队列复制 `review_id` 和 `catalog_hash`：

```json
{
  "review_id": "从 unmatched.json 复制审核编号",
  "action": "create",
  "confirmed": true,
  "expected_catalog_hash": "从 unmatched.json 复制64位目录哈希",
  "note": "已对照相近套路，确认关键转化不同，补齐方法边界。"
}
```

可增加完整 `draft` 对象人工修改草案，字段同目录但不用填写 `id`。`action: use_existing` 加 `routine_id` 表示改归已有套路；`defer` 或 `reject` 保留人工暂缓归属。使用一个新的独立输出目录，先预览，再应用已确认的决定：

```bash
python3 scripts/review_routine_candidates.py \
  --catalog backend/routine_catalog.json \
  --queue .runtime/routine-classification/my-run/unmatched.json \
  --decision /absolute/path/human-decision.json \
  --output .runtime/routine-classification/approved-01

# 增加 --apply 将扩展目录副本和修正写入上述独立目录
# 如有旧人工修正，用 --overrides /absolute/path/overrides.json 合并保留
```

默认预览不写文件、不调用 AI。`--apply` 只输出 `catalog.json`、`overrides.json`、`decision.json`；不覆盖基础目录或输入，也不创建正式套路。扩展目录自动分配新编号、更新版本，允许逐渐超过 300 项。相同输出已存在时拒绝覆盖。

后续分类显式使用新目录及修正：

```bash
python3 scripts/classify_question_patterns.py \
  --catalog .runtime/routine-classification/approved-01/catalog.json \
  --overrides .runtime/routine-classification/approved-01/overrides.json \
  --input /absolute/path/questions.jsonl \
  --output .runtime/routine-classification/next-run \
  --classify --limit 100
```

目录更新使旧 AI 缓存失效，人工修正继续优先。其他旧目录下的新套路草案需按扩展目录重新匹配再批准，以免重复新建。离线新建不会自动变成系统 API 的目录；API 的目录与人工确认队列存于当前账号独立状态文件，见[系统 API 说明](routine-matching-api.md)。双方共用匹配和审核逻辑，但保留各自明确选择的数据来源。

## 本轮验证

```bash
python3 -m unittest tests.test_routine_classification tests.test_routine_matching -v
```

测试输入是独立编写的 16 道模拟题；模型响应为固定假数据或故障模拟。覆盖同套路数字变式、空集/非空/单点边界、相似题面不同解法、综合题、缺解析、缺图、无匹配目录、代表题多样性、证据校验、重试、中断续跑、人工修正和文件冲突。测试禁止数据库连接，预演与报告模式禁止网络；另在新进程验证未加载应用和数据库模块。

这些检查验证脚本和数据契约，尚未验证真实 AI 的归组准确率。等题库稳定后先试分集合章约100题，审核并校准目录，再分批推广。后续入库沿用现有预览和确认流程；本脚本没有写回、发布或自动入库入口。
