# 阿里云离线发布操作

## 当前项目展示版

先完成 c9a8d37 版本的 23,255 道原题和审核账本导入。若仍遇到启动维护状态误判，按 [维护状态修复](question-data-maintenance-fix.md)修补原数据包脚本后重试。

在已验收、已提交且工作区无代码改动的 `main` 上制作新包：

```bash
.venv/bin/python deploy/build-offline-release.py \
  .runtime/server-sync/study-agent-showcase-offline.tar.gz --require-question-import
```

生成的包固定真实提交，包含完整 Git bundle、对应版本的启动/同步脚本、校验清单和发布元数据。当前展示版依赖未变化，复用已安装环境；候选环境检查仍在停站前执行。发布元数据强制先核对本轮题库和审核数据，未导入完成则退出。本轮实际包名、校验值与可直接粘贴的 Workbench 命令另外生成在 `.runtime/server-sync/`，请使用该版操作说明。

以下 c9a8d37 命令是此前依赖修复记录，保留用于追溯，发布展示版应使用新包的操作说明。

## 历史记录：c9a8d37 与 Python 3.14 依赖

目标提交：c9a8d378d01ef2599d6a45680956379e805c0055。

上次源码包已经读取成功；失败发生在候选环境下载 cryptography 时，尚未停站或替换网站。新版约 49 MB，包含源码和 25 个官方依赖 wheel，安装不需要访问 GitHub 或 PyPI。已通过完整离线依赖解析、包内校验及 6 项发布测试；服务器实际运行检查会在停站前执行。

此包适配日志中的标准 Python 3.14、Linux x86_64，要求 glibc >=2.28。启动器会先检查实际环境，不兼容则退出。

## 1. 在 Mac 终端定位新版包

```bash
open -R /Users/sqz/Desktop/study-agent/.runtime/server-sync/study-agent-c9a8d37-py314-offline.tar.gz
```

## 2. 用 Workbench 上传

如果终端仍在跟随日志，按 Ctrl+C 退出日志查看。
用 Workbench 文件管理器进入 /home/studyviewer，上传刚才定位的 study-agent-c9a8d37-py314-offline.tar.gz。

上传后的完整路径应为：
/home/studyviewer/study-agent-c9a8d37-py314-offline.tar.gz

Workbench 新版：左侧“文件管理”，打开目标文件夹后“上传文件”。旧版：顶部“文件 → 打开新文件树”，右键目标文件夹 → “上传文件”。
[阿里云文件管理说明](https://help.aliyun.com/zh/ecs/user-guide/manage-files)

## 3. 在服务器 root 终端整段粘贴

```bash
(
  set -Eeuo pipefail
  umask 077
  archive=/home/studyviewer/study-agent-c9a8d37-py314-offline.tar.gz
  [[ -f $archive ]] || { echo '请先上传新版离线包到 /home/studyviewer'; exit 1; }
  printf '%s\n' "9d7669edc4147d6f3e09be49910787fd9de970a671f0cee3001fd7ef0777b864  $archive" | sha256sum -c -
  release_dir=$(mktemp -d /root/study-agent-offline-py314.XXXXXXXX)
  tar -xzf "$archive" -C "$release_dir"
  bash -n "$release_dir/bootstrap-offline.sh"
  systemd-run --unit=study-agent-sites-offline-py314-c9a8d37 --collect \
    /bin/bash "$release_dir/bootstrap-offline.sh" \
    c9a8d378d01ef2599d6a45680956379e805c0055
) && journalctl -u study-agent-sites-offline-py314-c9a8d37 -n 80 -f
```

先应看到“使用离线 wheel 在候选环境安装；网站继续运行”。
看到“双站已同步到 c9a8d378d01ef2599d6a45680956379e805c0055”才算发布成功。Ctrl+C 仅退出日志查看，不停止后台发布。

## 4. 如发布失败，保存完整日志

退出日志查看后执行，联网恢复后把输出贴回：

```bash
journalctl -u study-agent-sites-offline-py314-c9a8d37 -n 200 --no-pager -l
```

发布沿用原来的任务等待、服务器数据备份、双站健康检查和自动回滚；离线包不包含本机题库、审核数据、网站密码或 API 配置。新版发布工具直接放在包中，不需要先提交这些工具到 GitHub。
