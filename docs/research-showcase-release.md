# 科研展示站的独立发布包

本轮先在本地完成、验收并推送 GitHub，再由项目负责人在阿里云 Workbench 手动发布。本文和打包器都不连接服务器；没有执行激活脚本就不能表述为已经上线。

## 发布范围

`scripts/build_research_release.py` 从当前工作树制作快照，只包含：

- `backend/showcase.py` 中 `ASSET_PATHS` 明确列出的前端文件，以及展示首页；
- 公开题库 manifest 明确列出的 JSON／题图；
- `backend/__init__.py`、`backend/showcase.py`、`backend/showcase_bank.py`；
- 包内校验器、独立激活脚本及发布清单。

打包器不递归复制整个仓库或整个前端目录，不包含数据库、`.env`、设置文件、凭据、本地调用器或原始私人学习记录。录制内容必须是已标注的构造学生案例。现有录制来源是本地正式业务代码加真实模型调用，不是线上正式站 HTML 抓取；发布不会改变这一来源说明。

发布清单记录本地真实 Git HEAD、是否包含未提交文件，以及每个文件的 SHA256 和大小。它快照当前文件，不假定工作树内容已经在 GitHub；未提交候选包必须与随后提交的内容再次核对。

## 本地验收与生成

在项目目录完成内容和浏览器验收后运行：

```bash
.venv/bin/python scripts/build_research_showcase.py --check
.venv/bin/python scripts/build_showcase_dataset.py --check
.venv/bin/python -m unittest tests.test_showcase tests.test_showcase_data tests.test_showcase_pipeline tests.test_showcase_bank tests.test_showcase_recordings tests.test_research_showcase -v
python3 scripts/build_research_release.py --output .runtime/research-showcase-release
```

浏览器检查继续使用 `tests/e2e/research_showcase_smoke.mjs`，沿用当前环境已安装的 Playwright 与浏览器路径，不为发布额外下载运行依赖。

输出目录包含本次 `research-<UTC时间>-<文件摘要>.tar.gz`、包 SHA256 文件、`SHA256SUMS`、`release.json` 和 `activate-demo.sh`。该目录是本地构建产物，不应将它与数据库或密钥一起提交。

建议先保留候选包做本地审查；全部代码和公开资源提交、推送后，再从同一提交重新生成最终包。清单里的 HEAD 才能准确关联 GitHub 版本。发布前可以在空临时目录解包并校验：

```bash
mkdir /tmp/study-research-release-check
python3 scripts/build_research_release.py --extract-archive <本次发布包路径> --output /tmp/study-research-release-check
python3 scripts/build_research_release.py --verify-directory /tmp/study-research-release-check
```

校验器检查完整公开白名单、逐文件摘要、15 章内容、两道全国卷与四位老师的完整管线记录、六类案例的三种实际输出、教学状态和实际生成结果。生成器真实拒绝候选是合法结果，不能为了通过发布检查补写一份成功答案。检查只确认记录和已核对答案的基本完整性，不替代全部数学证明或学习效果评测。

## GitHub 与 Workbench 的衔接

将本轮源文件、生成后的公开 HTML／JSON 和测试一起提交并推送，记录完整的 40 位提交 SHA。不要只推页面而漏掉新录制、题库清单、后端静态白名单或打包脚本。

Workbench 可以上传已验收的发布包与配套激活脚本，也可以在**独立的源码目录**检出该提交后重新打包。不要在正在运行的正式站目录执行 `git pull` 来完成这次 demo-only 发布。例如在一个此前不存在的新目录中：

```bash
git clone https://github.com/1314THER/study-agent.git /root/study-agent-research-source
git -C /root/study-agent-research-source checkout --detach <完整提交SHA>
cd /root/study-agent-research-source
python3 scripts/build_research_showcase.py --check
python3 scripts/build_showcase_dataset.py --check
python3 scripts/build_research_release.py --output /root/study-agent-research-release
cd /root/study-agent-research-release
sha256sum -c SHA256SUMS
```

目录已经存在时先核对其中内容，不覆盖、清空或强制重置。重新打包会产生自己的 UTC 时间和 tar 摘要，以本次实际输出为准，不混用另一份包的 SHA256。

## 激活前检查与正式切换

生成的脚本只接受现有独立展示布局：

| 对象 | 必须匹配 |
| --- | --- |
| systemd unit | `study-agent-demo`，当前处于运行状态 |
| 账号与组 | `studydemo` |
| 工作目录 | `/opt/study-agent-demo/current` |
| current | 指向 `/opt/study-agent-demo/releases/` 下的独立目录 |
| Python | `/opt/study-agent-demo/.venv/bin/python` |
| 启动参数 | `-m uvicorn backend.showcase:app --host 127.0.0.1 --port 8001 --workers 1` |

存在额外 unit override、外部题库覆盖、旧业务后端入口或不同目录布局时，脚本在停站前退出，要求人工核实，不猜测或改装服务。

先运行候选检查；将占位符换成本次实际包名与完整 SHA256：

```bash
bash activate-demo.sh <本次research包.tar.gz> <本次包SHA256> --check-only
```

它校验 tar 路径和类型、所有文件摘要与公开内容，建立独立候选目录，并以 `studydemo` 使用既有 venv 验证候选导入；不停止服务、不切换 `current`。同一个已经检查过的候选可以随后激活，不会覆盖既有不同内容：

```bash
bash activate-demo.sh <同一research包.tar.gz> <同一包SHA256>
```

激活顺序是：保留旧 release 与入口记录、备份旧公开文件 → demo drain 并等待请求清空 → 只停止 demo unit → 原子切换 `current` → 启动 demo → 检查本地健康、首页文件摘要和公开 demo 健康。

脚本不更新 Python 环境、不安装依赖、不修改 Caddy 或 systemd unit，也不停止、重启或修改正式站服务、数据和 API 配置。锁会与已存在的双站同步锁协调，避免两种发布同时运行。

## 失败与回滚

停站或切换后的失败、SIGINT、SIGTERM 都会尝试恢复原 `current`、重启旧 demo 并核对健康；停站前失败则退出 drain。无法恢复时脚本打印明确的人工处理提示，不把回滚尝试称为已成功恢复。

旧 release 不删除。备份位于 `/opt/study-agent-demo/backups/<release_id>/`，含原入口、旧公开文件及新清单；候选检查失败不影响旧入口。发布成功后再用浏览器确认章节导航、对比结果、公式、题库选题、打印及手机布局。

本说明只提供可审查操作流程；是否已经上传、激活和线上验收，应以实际 Workbench 输出与浏览器结果为准。
