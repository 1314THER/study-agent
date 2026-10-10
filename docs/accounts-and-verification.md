# 账号系统、共享母题与验证码服务

核验日期：2026-10-09。推荐先开放邮箱验证码注册；国内短信等资质获批后再接。

## 已实现的用户流程

启动页提供游客登录、创建账号、账号登录三个入口。游客明确点击后才创建原有两小时临时工作区；正式账号用邮箱验证码注册、设置密码和一把 DeepSeek API Key，用户名或邮箱加密码登录。登录有效期七天，退出会在服务器撤销会话。未配置邮件发送服务时，注册页面明确关闭注册，已有账号和游客入口仍可使用。

用户可以在设置页更换自己的密钥。密钥只在服务器解密后用于 DeepSeek 官方接口，页面不回显已保存的密钥。注册检查格式；余额、有效性和网络可达性由设置中的连接测试确认，不在注册期间调用付费模型。教学、识图、批改和解题统一使用 DeepSeek，教程入口为 `/deepseek-guide.html`。

目前手机验证码接口明确关闭；没有假验证码或返回验证码给浏览器的测试后门。普通用户忘记密码的自助流程暂未加入。

## 数据与权限

| 数据 | 位置与归属 | 权限 |
|---|---|---|
| 用户、密码哈希、验证码哈希、会话哈希、加密 API key | `STUDY_AUTH_ROOT/accounts.db`，用户主键 `users.id` | 仅服务端处理 |
| 公共母题、标准解析、套路与闯关地图 | `STUDY_AUTH_ROOT/catalog.db`，按版本发布 | 仅主人 `studyadmin` 发布/编辑 |
| 用户题库、错题、题单、掌握状态、复习日历、教学、后台任务 | `STUDY_AUTH_ROOT/users/user-<id>/` | 仅对应登录账号 |
| 游客数据 | 独立 `guests/session-<token>/`，两小时过期 | 仅对应游客会话 |
| 原有主人数据 | 原项目 DB 与 `backend/` 配置位置，或显式 `STUDY_OWNER_DATA_DIR` | 主人继续使用 |

题库及学习记录增加 `user_id`。共享题目使用 `catalog_id` 关联公共库，`user_id=NULL`。学习引擎保留现有 SQLite 工作区模式：把共享定义投影到个人库，与个人错题及进度关联，而不复制主人的作答、密钥、设置和私人题目。默认投影 ID 为负数，个人自增 ID 为正数；用户已有同题时复用该题 ID，以保留原错因记录。

共享母题更新时只更新定义，保留个人进度。撤下的题保留为只读历史记录，移出母题题单；撤下的套路移出当前学习地图。AI 生成的个人变式保存在用户工作区。题库写入、删除、来源改动和母题/地图编辑在数据层检查权限，因此直接调用接口或 AI 工具也不能修改公共母题。

`studyadmin` 为保留账号，不能通过注册抢注。原先的 Caddy Basic Auth 账号不是应用数据库账号；不能从 Caddy 密码哈希取得原密码，需在服务器通过引导命令创建应用主人账号，可以自行输入相同密码。

## 阿里云短信：个人备案够不够

**仅个人 ICP 备案、个人实名认证不足以申请当前国内短信自用签名。** 阿里云最新资质说明明确：个人认证自用资质无法通过签名实名报备；可以提供企业授权申请他用资质，或将云账号升级为企业认证。所需材料涉及统一社会信用代码证照、法人/负责人和管理员身份信息；他用签名还需授权委托书。具体以控制台与运营商审核结果为准。[阿里云资质材料](https://help.aliyun.com/zh/sms/user-guide/qualification-application-description/)

可行流程是：取得适用主体资质 → 云账号认证/他用授权 → 短信资质审核 → 签名与验证码模板审核 → 运营商实名报备 → 配置 API 凭据与限额。能开通云产品不等于短信签名获批；个人网站备案号也不是短信主体证照。

腾讯云也要求个人认证账号准备企业证件和授权材料，且已停止网站、公众号、小程序等签名类型。迁移到腾讯云不会解除这一门槛。[腾讯云签名材料](https://cloud.tencent.com/document/product/382/37794)、[规则变更公告](https://cloud.tencent.com/document/product/382/116397)

因此本版使用邮箱验证。SMTP 可接阿里云邮件推送或获服务商允许的邮箱服务。发信域名控制、发信地址/SMTP 凭据、投递额度是邮件配置重点；阿里云新发信域名需要通过 SPF、DKIM、DMARC 和 MX 验证。建议使用专用子域名，避免影响原邮箱。邮件推送的账号准入和额度仍需在中国站控制台确认。[配置流程](https://help.aliyun.com/zh/direct-mail/getting-started/simplified-procedure-of-configuring-email-delivery)、[发信域名配置](https://help.aliyun.com/zh/direct-mail/user-guide/configurations/)

## ICP 备案与注册服务的关系

验证码服务资质、网站 ICP 备案、公开 AI 服务登记是不同事项。不能仅凭个人备案直接推断“所有登录系统都禁止”或“公开 AI 学习平台一定允许”。个人/非经营性网站仍需保持备案信息与实际服务一致；重庆有具体个人网站规则。建议向阿里云备案工单描述“免费学习工具、邮箱注册、个人数据保存、用户自带 DeepSeek key、公共母题由主人维护”，确认现有备案服务内容是否需要变更。若以后收费、经营平台或改变服务内容，需按实际业务重新确认主体和许可。[非经营性备案办法](https://www.miit.gov.cn/gyhxxhb/jgsj/cyzcyfgs/bmgz/xxtxl/art/2024/art_84a0cfa0ebd049bbbe751dca9a008e56.html)、[重庆备案规则](https://help.aliyun.com/zh/icp-filing/icp-filing-regulations-for-chongqing)

面向公众提供 AI 功能还应确认属地网信办登记路径。网信办公告明确，直接调用已备案模型能力的应用/功能由地方网信办开展登记，并有模型名称及备案/上线信息公示要求。用户自带 key 不自动免除平台相关义务；本项目是否适用须按实际服务范围确认。[网信办 2026 年公告](https://www.cac.gov.cn/2026-05/13/c_1780413225190669.htm)

## 本地预览

使用安装了 `requirements.txt` 的 Python。只需在终端配置环境变量，不将密钥贴到聊天或提交 Git。

```bash
python3 scripts/bootstrap_owner.py --generate-key
# 把生成值安全保存，并作为 STUDY_AUTH_ENCRYPTION_KEY 环境变量配置一次。
python3 scripts/bootstrap_owner.py
python3 scripts/run_accounts.py --port 8002
```

打开 `http://127.0.0.1:8002/login.html`。本地脚本只监听 loopback，并为该地址使用非 Secure 的本地 cookie；生产 HTTPS cookie 默认启用 Secure。不配置 SMTP 时可检查三入口、游客和已初始化主人登录。SMTP 设置参考 `.env.example`，它仅是变量清单，启动器不自动执行 `.env`。

## 生产切换（尚未部署）

1. 备份主人 DB、`backend/settings.json`、`patterns.yaml`、`board_order.yaml` 和运行数据；新系统首次启动执行兼容迁移，不删除原题目。账号库、个人目录、公共库和加密主密钥都要纳入备份。
2. 用受限的 systemd `EnvironmentFile` 设置 `STUDY_AUTH_ENABLED=1`、稳定的 `STUDY_AUTH_ROOT`、`STUDY_AUTH_ENCRYPTION_KEY`、正式域名的 `STUDY_AUTH_ORIGIN`、`STUDY_AUTH_COOKIE_SECURE=1` 和 SMTP 变量。该目录应由运行正式服务的账号独占，文件权限 600/目录 700。加密密钥丢失后原用户 key 无法解密。
3. 在同样环境下运行 `scripts/bootstrap_owner.py`，通过隐藏输入初始化主人。忘记主人密码时加 `--reset-password`；此操作撤销全部主人会话。
4. 现有 `backend.main:app` 在 `STUDY_AUTH_ENABLED=1` 时自动启用三入口。`/health` 应显示 `mode=accounts`。仅在确认这个模式及匿名 API 不可访问主人数据后，把原 Caddy 整站 Basic Auth 改成转发应用登录入口；不能先移除旧保护。
5. Caddy 当前 `/` 是独立备案入口页。如保留它，将其主入口链接改为 `/login.html`；如改为应用三入口，转发 `/` 并保留页面的备案展示。此仓库未替换正在运行的 Caddy 配置。
6. 原独立 demo 站可以继续使用旧两小时演示；正式账号站同域游客与账号数据分离。需要游客继续调用共享 AI 时，显式设置只读 `STUDY_DEMO_AI_CONFIG`，通过现有 `deploy/prepare-demo-ai.py` 生成只含 DeepSeek 的快照；注册用户永不继承此快照的 key。
7. 配置实际发信域名/SMTP、发送额度和监控后，再验证真实邮件到达、验证码过期/重发/退出、两个账号隔离及母题权限。自动测试使用模拟邮件和模型调用，没有发送真实邮件或消耗 AI 额度。

当前实现适用于现有单进程 SQLite 服务。用户增长后可将中央账户库、共享题库和学习记录迁往 PostgreSQL，验证码限流迁往 Redis；这不影响 `user_id` / `catalog_id` 的归属规则。
