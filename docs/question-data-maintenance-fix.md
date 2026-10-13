# 本次题库导入维护检查修复

导入程序将进程保留的启动变量误认为实时维护状态。代码发布成功后，该变量仍可为 1，而实时状态已经通过内部接口解除。此次失败发生在任何题库写入之前。以下命令仅修补已解压脚本与其校验记录，不需要重传数据包。修复保留实时维护检查、部署锁、备份和回滚。

针对本次日志中的目录 `/root/study-agent-question-data.AUHpDGb1`，先 Ctrl+C 退出日志查看，再在服务器 root 终端粘贴：

```bash
(
  set -Eeuo pipefail
  cd /root/study-agent-question-data.AUHpDGb1
  /opt/study-agent/.venv/bin/python - <<'PY'
from pathlib import Path
import hashlib

folder = Path('/root/study-agent-question-data.AUHpDGb1')
script = folder / 'import-question-data.sh'
old_sha = '5e23c087a8434df2356d1b8ad00fc8040523b9645df3bbdbbf1e9ed2745748ed'
new_sha = 'c1db1f699f0cd9bd9c623f182edf40ea0d4faaf48ebcdfc3a1e1eab4b2064e03'
data = script.read_bytes()
if hashlib.sha256(data).hexdigest() not in (old_sha, new_sha):
    raise SystemExit('脚本与已验证版本不同，未修改，请保留日志。')
guard = ("if environment.get('STUDY_DEPLOY_DRAIN', '0') == '1':\n"
         "    raise SystemExit('主人启动配置仍开启维护状态，请先处理原维护操作')\n").encode()
replacement = ("# The startup environment can retain STUDY_DEPLOY_DRAIN=1 after a successful\n"
               "# release. The internal status endpoint below is the live maintenance state.\n").encode()
updated = data.replace(guard, replacement)
if hashlib.sha256(updated).hexdigest() != new_sha:
    raise SystemExit('修补结果校验失败，未修改。')
sums = folder / 'SHA256SUMS'
lines = sums.read_text().splitlines()
matches = [i for i, line in enumerate(lines) if line.endswith('  import-question-data.sh')]
if len(matches) != 1 or lines[matches[0]].split('  ', 1)[0] not in (old_sha, new_sha):
    raise SystemExit('脚本校验记录不同，未修改。')
lines[matches[0]] = new_sha + '  import-question-data.sh'
script.write_bytes(updated)
sums.write_text('\n'.join(lines) + '\n')
print('导入脚本已修复；实时维护检查和数据校验保留。')
PY
  sha256sum --check --strict --quiet SHA256SUMS
  bash -n import-question-data.sh
  systemd-run --unit=study-agent-question-data-retry-20261013 --collect \
    /bin/bash /root/study-agent-question-data.AUHpDGb1/import-question-data.sh
) && journalctl -u study-agent-question-data-retry-20261013 -n 100 -f
```

看到“原题池与审核数据已导入：23,255 道原题。”才算完成。若仍失败，用以下命令保存新日志：

```bash
journalctl -u study-agent-question-data-retry-20261013 -n 200 --no-pager -l
```

如果实时状态仍在维护中，程序继续退出；不要强制解除维护或删除其它发布操作的维护配置。
