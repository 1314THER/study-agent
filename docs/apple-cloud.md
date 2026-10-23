# Apple 客户端与云端数据服务

本次增加 SwiftUI 客户端、共享 `/api/v1` 服务、PostgreSQL 数据层及迁移工具。原有 `start.sh` / `backend.main:app` 在未配置 `STUDY_DATABASE_URL` 时保持原来的 SQLite 工作模式。配置此变量后，入口切换到云端应用；**先在独立环境演练，不能直接指向正在使用的库**。

## 当前功能

- iPhone、iPad、Mac 共用账号、题库、批改、教学、进度和后台任务 API。
- 邮箱/用户名加密码登录；邮箱验证码注册。注册仍要求自己的 DeepSeek API Key。浏览器注册入口已恢复；未配置 SMTP 时明确关闭提交。云端未提供游客工作区，页面会按服务器配置隐藏游客入口。
- iPad / iPhone 使用 PencilKit 保存本机笔迹并导出作答图片；iPhone 支持相机，Mac 支持文件选择和拖入。PDF 可后台识别题目，作答 PDF 可做 OCR。
- 本地 SQLite 按服务器和账号隔离，缓存题目、任务、教学、进度及草稿；笔迹和题图保存在对应缓存目录。退出前提示未提交草稿，确认后清除个人缓存。离线草稿暂不跨端同步。
- 本地 WebKit 使用项目已有 KaTeX、JSXGraph、Three.js 和受限几何渲染器，不加载 CDN，不向网页传递令牌。
- 服务器单进程、两个后台 worker，任务在数据库持久化。网络重试使用同一请求编号；服务器重启把未完成任务标记为中断，不自动重复消耗 AI。

云端网页位于 `/home.html`，与原生客户端使用相同服务。旧题目/教学读取路径有兼容入口，旧页面链接进入新版学习台。原有完整的原题采集、分类、审核工具仍可在本地 SQLite 版本使用；迁移后的管理记录在云端受管理员权限保护。**这并不表示原有全部管理界面和维护脚本已经逐项迁成云端版本**；正式切换前需按实际管理工作流逐项验收。

云端已提供原题导入、准备 AI 解析、确认/排除/暂缓审核以及发布公共题。既有采集工具产出的 JSONL 可通过 `scripts/import_cloud_records.py --server https://你的域名 --file /本地/候选题.jsonl` 导入；命令使用隐藏的主人密码输入，结束后撤销本次设备会话。缺失题图的题目需要先补齐资料，AI 准备任务不会自动公开题目。

## 本机启动

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/run_cloud.py --sqlite --bootstrap-owner
```

首次在隐藏输入中创建 `studyadmin`。之后省略 `--bootstrap-owner`，在浏览器打开 `http://127.0.0.1:8003/login.html`。此开发模式的数据放在被 Git 忽略的 `.cloud/`，有一个稳定的本地开发加密密钥；不读取或覆盖原项目的题库。

Mac App 和 iOS 模拟器可把服务器地址设为 `http://127.0.0.1:8003`。真机的 localhost 指向设备自己，须使用可访问的 HTTPS 服务。仅 loopback 允许 HTTP；不要为真机关闭全局传输安全检查。

## Xcode 工程

打开 `apple/StudyCoach/StudyCoach.xcodeproj`，选择 `StudyCoach` scheme 和目标设备。最低 iOS/iPadOS 18、macOS 15；在 Signing 中选择自己的开发团队后进行真机安装或测试分发。项目没有预填团队、证书或配置描述文件。

工程使用同目录 Swift Package 的 `StudyCore`，没有外部 Swift 包依赖。调整 Swift 文件列表后可运行：

```bash
.venv/bin/python scripts/create_apple_project.py
.venv/bin/python scripts/sync_apple_resources.py
swift test --package-path apple/StudyCoach
```

修改网页几何渲染器或 vendor 资源后，运行资源同步脚本；保留附带许可证。Mac 项目构建：

```bash
xcodebuild -project apple/StudyCoach/StudyCoach.xcodeproj -scheme StudyCoach \
  -configuration Debug -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build
```

iPhone/iPad 需要 Xcode 安装对应 iOS SDK 和模拟器组件。本机当前 Xcode 报告缺少 iOS 26.5 平台组件，因此这两个目标的编译与设备行为尚待验证；Pencil、相机、真实邮件与签名分发也需真机/正式配置验收。无签名构建不等于可分发版本。

Mac 无签名预览已能启动，但本机实测无法写入受保护钥匙串。完整登录需要通过 Xcode 配置开发团队并签名；客户端不会把登录凭证降级存入普通文件。Swift 测试使用内存凭证容器验证网络流程，不能代替签名后的系统钥匙串验收。

## PostgreSQL 初始化和切换

使用独立业务数据库、专用运行账号，只监听受控内网/loopback。通过服务环境文件设置：

```text
STUDY_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/study
STUDY_CLOUD_ROOT=/srv/study-cloud
STUDY_AUTH_ENCRYPTION_KEY=<稳定的 Fernet 密钥>
STUDY_AUTH_ORIGIN=https://你的正式域名
STUDY_AUTH_COOKIE_SECURE=1
```

真实凭据不写入仓库。迁移已有账号时必须使用原加密主密钥；账号数据库备份不能替代该密钥。SMTP 使用现有 `STUDY_SMTP_*` 配置，详见 `accounts-and-verification.md`；本次测试没有向外发送邮件或调用付费 AI。

1. 停止旧站写入并等后台任务结束，保留旧服务配置和数据目录。在线 SQLite backup 保证每个文件一致，但跨文件业务一致性仍需要停写。
2. 在停写期间创建快照（输出目录必须在源目录外）：

   ```bash
   .venv/bin/python scripts/migrate_cloud.py snapshot \
     --owner /原主人数据目录 --accounts /原账号目录 --output /私有备份/本次快照
   ```

   没有账号版时省略 `--accounts`。快照包含账号库、公共库、每个正式用户的题库/掌握/任务/教学/分析/原题池/审核库及题图、上传和题源文件；不会迁移游客会话。快照目录 0700、文件 0600，包含私有数据，应纳入加密备份。自定义过数据路径时先核对清单，不依赖默认路径猜测。
3. 在空的测试目标库执行 `.venv/bin/alembic upgrade head`，再演练：

   ```bash
   .venv/bin/python scripts/migrate_cloud.py import --bundle /私有备份/本次快照 --asset-root /srv/study-cloud/assets
   .venv/bin/python scripts/migrate_cloud.py import --bundle /私有备份/本次快照 --asset-root /srv/study-cloud/assets --apply
   .venv/bin/python scripts/migrate_cloud.py verify --bundle /私有备份/本次快照 --asset-root /srv/study-cloud/assets
   ```

   未指定 `--apply` 不写库。UUID 映射依据“账号＋资源类型＋旧 ID”生成，公共题投影映射到同一题目；同一快照重复执行不会重复导入。缺失题目引用、账号冲突或文件校验失败会中止导入，不猜测关联。
4. 不迁移旧 Cookie、验证码和设备会话，用户需要重新登录。没有原应用账号的主人会导入为禁用账号：执行 `scripts/bootstrap_owner.py --reset-password --set-api-key` 后使用。已有主人重置密码会同时撤销浏览器和原生会话。
5. 用两名测试用户验收网页与三端的数据、题图、历史作答、教学及权限，再在正式目标重复演练步骤，最后切换反向代理。Uvicorn **只运行一个进程**，例如 `uvicorn backend.cloud_app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1`。

云端保留五个 schema：`auth`、`content`、`learning`、`runtime`、`admin`。原题池和审核等暂存为保留原始字段的管理记录，历史套路/闯关等学习记录也保留旧字段和新 UUID 引用，供后续细化工作流。JSON 数据不替代关键的账号、题目版本、作答、教学和任务关系约束。

## 回滚与验证

切换后需要回滚时先再次停写，并导出云端新增数据：

```bash
.venv/bin/python scripts/migrate_cloud.py export --output /私有备份/cloud-before-rollback.jsonl
```

导出覆盖全部云端结构化记录，另行备份 `STUDY_CLOUD_ROOT/assets` 和主密钥。恢复旧 SQLite 快照只恢复切换前状态；云端新增写入必须经核对、转换后补回，不能假定导出文件会自动恢复成旧 SQLite。

```bash
.venv/bin/python -m unittest tests.test_cloud tests.test_cloud_migration
# 可选测试依赖，仅用于本机隔离 PostgreSQL，不用于生产：
.venv/bin/python -m pip install pgserver
.venv/bin/python scripts/test_cloud_postgres.py
```

测试运行时使用临时数据库、模拟邮件和不消耗 AI 的确定性题目。PostgreSQL 集成测试显式拒绝未标记的数据库，避免误清理生产表。

### 本机验证记录（2026-10-18）

- 隔离 PostgreSQL：从 Alembic 初始迁移建库，19 项云端与迁移测试全部通过，覆盖账号隔离、刷新令牌轮换、重复提交、历史题目版本及迁移完整性。
- SQLite 兼容模式：18 项通过，1 项 PostgreSQL 专用约束测试跳过。
- Swift 共享模块：5 项通过，覆盖缓存/草稿持久化、账号隔离、离线资源及并发刷新令牌。
- macOS arm64 Debug 未签名工程构建成功；网页已用临时测试账号验证登录、选题、提交和批改。
- iOS/iPadOS 编译与真机、签名后的系统钥匙串、真实 SMTP 和生产迁移尚未验收，不能据此视为已经完成发布。
