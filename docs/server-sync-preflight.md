# 图谱版本同步前检查 · 2026-10-13（历史记录）

以下记录对应图谱版本的检查阶段。后续代码发布到 `c9a8d37`、离线依赖和 23,255 题导入操作见各自说明；当前项目展示站的实现与验证见 [展示站说明](showcase-demo.md)。历史检查中的 SHA 与状态不代表当前待发布版本。

## 检查结果

| 检查 | 结果 |
|---|---|
| 全量 Python 测试 | 651 项通过，包含部署快照与跨电脑题图读取回归 |
| 前端回归 | 10 组全部通过 |
| 图谱浏览器验收 | 图谱、已有关系、题目跳转、分页、拖动保存与刷新、新套路录入、导航权限、手机布局通过 |
| 保存故障恢复 | 注入一次 503，重试成功后清除错误样式，并保留正确布局 |
| 几何教学浏览器验收 | 五个场景、提示、答案、跳过、刷新恢复和手机回看通过 |
| 干净代码副本启动 | 9 个页面/API 通过；基础图谱 288 个套路；无私有接入时本地 Codex 显示不可用 |
| Python/JavaScript 语法 | 103 个 Python 文件与 19 个前端脚本通过；历史调试占位 `_gen.py` 沿用既有排除规则 |
| 依赖 | `pip check` 通过 |
| 本机持久数据 | 题库、掌握记录、原题池、审核账本、任务账本的 SQLite quick_check 全部通过 |
| 发布脚本 | Bash 语法与嵌入 Python 语法通过；完整快照往返、WAL、摘要、链接、目标检查与磁盘估算有测试 |
| GitHub main | 已只读核对，与开始检查时的本地提交一致：`a457ec1bcd32d65e039c5f75132c46c4059d541c` |

测试使用临时数据库与模拟模型，没有调用收费 AI。Linux 的 systemd、实际磁盘权限、Caddy、服务切换和失败回滚尚须在目标服务器验收，本机结果不能替代这些检查。

## 本轮修复

1. 图谱保存重试成功后正确清除红色错误状态。
2. 题图与审核原件读取支持历史 `.runtime/question-pool/` 路径移动到另一台电脑，保留原始出处记录和访问范围检查。
3. 发布备份加入原题池、套路审核账本、题源原件、题图、新套路目录、图谱布局及默认账号目录；每个文件有 SHA-256 与大小记录，SQLite WAL 归并并检查完整性。正常更新保留运行文件，失败时从完整快照恢复，旧快照仍可回滚。
4. 停站前检查备份空间；自定义数据或账号目录需另行制定备份范围。依赖检查加入账号功能所需的 cryptography。

这些图谱与快照修复已包含在 `c9a8d378d01ef2599d6a45680956379e805c0055` 中。后续展示版发布应采用对应新版本的离线操作说明，不能直接沿用历史 SHA。

## 只更新代码的同步顺序

在 Mac 查看本轮变更并提交、推送后，运行以下命令取得新的完整 SHA：

```bash
cd /Users/sqz/Desktop/git
git status --short
git diff --stat
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

先确认工作区修复已经提交，且最后两行 SHA 一致。在服务器 root 终端使用[统一发布启动脚本](../deploy/bootstrap-sites.sh)；把示例中的占位值替换为新 SHA：

```bash
systemd-run --unit=study-agent-sites-sync --collect /bin/bash /root/study-agent-bootstrap-sites.sh REPLACE_WITH_NEW_FULL_COMMIT_SHA
journalctl -u study-agent-sites-sync -n 120 --no-pager
```

上述命令沿用已经安装在 `/root/` 的启动脚本；若该文件还没有，按 [Ubuntu 部署说明第三步](../deploy/ubuntu.md#第三步统一发布主人站与游客站)先安装。仅在旧服务确实没有 `/_internal/deploy-status`、并确认所有任务结束的首次升级中加 `--bootstrap`。日常同步会暂停新请求、等待任务结束、备份、更新双站并检查入口。

成功后按 [第四步验收](../deploy/ubuntu.md#第四步验收)检查两个服务、HTTPS 和主人入口保护，再在主人站验证“套路图谱”和对应审核题目。游客页面不显示主人专用的图谱与审核入口。

## 数据同步范围

GitHub 不包含下列持久数据：

| 数据 | 默认路径 |
|---|---|
| 原题池 | `.runtime/question_pool.db` |
| 审核结果、人工决定及匹配进度 | `.runtime/routine-review.sqlite3` |
| 题源原件、转换结果和下载记录 | `.runtime/question-pool/` |
| 已保留的题图 | `.runtime/question-assets/` |
| 新套路目录及审核记录 | `.runtime/routine-matching/state.json` |
| 图谱位置 | `.runtime/routine-matching/graph.json` |

仅更新代码会保留服务器上已有的数据，不会把本机审核结果带过去。2026-10-13 已生成本机 23,255 道原题的独立数据包，含审核账本、题图及来源原件；见 [题池数据上传与导入说明](question-data-server-import.md)。导入工具保留已有服务器内容，编号、内容或附件冲突时拒绝写入；不修改账号、密码、API 配置和学习记录。

`runtime_snapshot.py` 用于同一服务器的完整备份与回滚。跨电脑题池迁移使用新的定向导入工具；不能用旧版五文件导入脚本迁移本轮审核数据，也不能把本机完整回滚快照直接覆盖服务器账号。数据包尚需用户手动上传并执行导入，生成本地包不代表服务器已更新。
