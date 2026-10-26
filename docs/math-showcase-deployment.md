# math.150.chat 独立展示站

## 与现有 demo 的边界

| 项目 | 新展示站 | 现有 demo |
| --- | --- | --- |
| 域名 | `math.150.chat` | `demo.150.chat` |
| 页面风格 | 浅色答题纸、蓝色批注 | 现有深色 demo |
| Linux 服务 | `study-agent-math-showcase` | `study-agent-demo` |
| Linux 用户 | `studymath` | `studydemo` |
| 文件目录 | `/opt/study-agent-math-showcase/` | `/opt/study-agent-demo/` |
| 本机端口 | `127.0.0.1:8002` | `127.0.0.1:8001` |
| 请求能力 | 只读页面和 JSON；不调用模型、不写业务数据 | 由既有 demo 自己管理 |

站点只开放 80/443 给 Caddy，8002 只监听本机回环地址，不需要加入 ECS 安全组。新站把案例页、专题目录、站点样式、只读后端和 KaTeX 资源组成独立发布包；不会把用户数据库、环境变量、正式站代码或旧 demo 文件打入包中。案例页清楚标记构造学生作答，以及批改、教学、变式分别保存的事实。

## 本地生成与打包

在项目根目录生成公开数据并制作独立包：

```bash
python3 scripts/build_math_showcase.py
python3 scripts/build_math_showcase_release.py --output .runtime/math-showcase-release
```

打包器会核对生成 JSON 与已保存展示记录一致，只打入显式白名单资源。输出目录包含发布 tar.gz、单独的激活脚本、`SHA256SUMS` 和发布信息。`release.json` 会记录 Git HEAD 及工作树是否含有未提交改动；如果准备长期维护，建议先把审核过的实现提交，再从该提交重建最终包。不要把 `.runtime/math-showcase-release/` 当成源代码提交。

## 阿里云 DNS 与 ECS 准备

1. A 记录已添加后，在 ECS 上运行 `getent ahostsv4 math.150.chat`，确认解析结果包含这台 ECS **当前**的公网 IPv4 地址；解析尚未更新时先等 DNS 生效，不要照抄旧部署文档里的历史 IP。
2. 确认 ECS 安全组允许 TCP 80 和 443 入站，Caddy 才能签发并续期 HTTPS 证书。不要开放 8002。
3. 通过 Workbench 上传发布目录中的两个文件（tar.gz 和 `activate-math-showcase.sh`）及 `SHA256SUMS`，例如放到 `/tmp/math-showcase-release/`。

## 在 ECS 激活

将命令里的 tar.gz 文件名换成上传的实际文件名；哈希可以从 `SHA256SUMS` 的同名行复制：

```bash
cd /tmp/math-showcase-release
sha256sum -c SHA256SUMS
sudo bash ./activate-math-showcase.sh ./math-showcase-<时间和摘要>.tar.gz <该 tar.gz 的 64 位 SHA256>
```

激活脚本会先核对包摘要和包内文件白名单，再创建专用 `studymath` 系统账号及 `/opt/study-agent-math-showcase/` 独立目录，安装独立 systemd unit，在本机启动 8002 健康检查通过后才让 Caddy 导入 `math.150.chat` 并 reload。它不会停止或改写 `study-agent-demo`、`study-agent`，也不会安装 Python 包。切换前会自动备份 Caddyfile、math 站点片段、unit 和当前版本；失败时会尝试恢复。

部署后检查：

```bash
sudo systemctl status study-agent-math-showcase --no-pager
curl --noproxy '*' -fsS http://127.0.0.1:8002/health
curl -I https://math.150.chat/
```

日志：

```bash
sudo journalctl -u study-agent-math-showcase -n 80 --no-pager
```

若要撤回本次激活，使用安装成功时终端打印的备份目录：

```bash
sudo bash /tmp/math-showcase-release/activate-math-showcase.sh --rollback /opt/study-agent-math-showcase/backups/<时间和摘要>
```

首次安装的回滚会移除 math 站点的 Caddy 导入、片段和服务配置；以前部署过 math 站点时会恢复备份中原有版本。发布目录和备份保留，便于后续排查。

## 与既有发布脚本共存

新站有独立 unit 和独立 Caddy 片段。现有 `deploy/install-demo.sh` 会对它自己的 demo service/片段操作，并在原 Caddyfile 中增加 demo 导入；现有双站同步脚本在回滚时恢复它开始同步前的 Caddyfile 快照。因此不要在运行中的同步或 demo 安装过程中并行激活新站。新站不改变这些脚本管理的服务端口和目录。
