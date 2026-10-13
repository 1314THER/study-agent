# 上传本机 23,255 道原题及审核结果

之前的离线代码包不含题库。本次已单独生成数据包：
`/Users/sqz/Desktop/git/.runtime/server-sync/study-agent-question-data-20261013.tar.gz`

压缩大小约 413 MiB，包含 23,255 道独立原题、61 个来源、23,536 条出处、两批审核账本和 2,708 个原件及图片文件。当前审核批次中 17,005 道有主套路匹配；原有人工审核状态保留。两批审核的 46,510 条快照并不是 46,510 道独立题。

已通过 35 项迁移/离线发布测试，以及完整数据的试导入、图谱计数、原件跨电脑路径读取和配置保留检查。压缩包每个文件有 SHA256 校验，数据库由 SQLite backup API 导出，已包含 WAL 中的提交。

先按 [离线代码发布说明](offline-server-sync.md)完成代码更新到 `c9a8d378d01ef2599d6a45680956379e805c0055`，看到“双站已同步到…”后再导入数据。如果服务器还没到这个版本，数据导入会在停站前退出。

## 1. 在 Mac 终端定位数据包

```bash
open -R /Users/sqz/Desktop/git/.runtime/server-sync/study-agent-question-data-20261013.tar.gz
```

## 2. 手动上传

切换到阿里云 Workbench，在文件管理器中进入 `/home/studyviewer`，上传 `study-agent-question-data-20261013.tar.gz`。

上传后的完整路径必须为：
`/home/studyviewer/study-agent-question-data-20261013.tar.gz`

## 3. 在服务器 root 终端粘贴

```bash
(
  set -Eeuo pipefail
  umask 077
  archive=/home/studyviewer/study-agent-question-data-20261013.tar.gz
  [[ -f $archive ]] || { echo '请先上传题库数据包到 /home/studyviewer'; exit 1; }
  printf '%s\n' "804539c6a7d7b1310a5b51948b1dd35f5de241566592f7ef290732a325a29f0d  $archive" | sha256sum -c -
  release_dir=$(mktemp -d /root/study-agent-question-data.XXXXXXXX)
  tar -xzf "$archive" -C "$release_dir"
  bash -n "$release_dir/import-question-data.sh"
  systemd-run --unit=study-agent-question-data-20261013 --collect \
    /bin/bash "$release_dir/import-question-data.sh"
) && journalctl -u study-agent-question-data-20261013 -n 100 -f
```

看到“原题池与审核数据已导入：23,255 道原题。”才算完成。随后登录主人站，在原题池、套路审核及套路图谱中查看。

Ctrl+C 只退出日志查看；发布在 systemd 后台继续运行。

## 4. 如有失败

退出日志查看后保存完整输出，联网恢复时贴回：

如果日志为“主人启动配置仍开启维护状态”，本次包的启动变量检查会误判已经正常退出维护的服务。无需重传数据包，按 [维护检查修复说明](question-data-maintenance-fix.md)精准修补已解压脚本并重新启动导入；实时维护状态检查仍保留。

```bash
journalctl -u study-agent-question-data-20261013 -n 200 --no-pager -l
```

程序在网站运行时先检查文件、空间和数据库冲突；遇到同编号不同题目、同名不同附件或另一批未归档审核任务会退出，保留服务器内容。预检通过后暂停新写入，等待任务结束；停站后从最新服务器数据重新合并，再备份并安装。安装或启动失败时自动恢复这次变更。若自动恢复未完成，保留维护配置、候选和备份目录，按日志中的具体路径处理，不要删除它们。

本包只导入主人原题池、审核账本和附件，不修改服务器已有账号、密码、API 设置、正式学习库或游客数据。原题仍保留当前原题池/审核状态。
