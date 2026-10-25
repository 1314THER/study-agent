# 本地模型入口与云端占位

主人在原题池选中题目后，可以点击“用本地 Codex CLI 准备解析”，依次执行 Solver、Verifier、Formatter。解析仍保存在原题池中，核对原答案并预览后才确认入库。标准“准备 AI 解析”继续使用 DeepSeek。解析记录保存 `model_provider`，供核对来源。

公共代码仅提供本地模型接口和占位按钮。真正的 CLI 调用和 Codex 套路匹配实现位于 `.local-codex/` 与 `backend/routine_codex.py`；这些文件及专项测试被 Git 忽略，之前已跟踪的 CLI 文件也取消了跟踪，本地文件仍保留。仅克隆仓库不会获得这些实现。

本地启动脚本检测私有接入后设置 `STUDY_LOCAL_CODEX=1`，服务只监听本机地址。服务还会检查请求来自本地，带转发标头或公开域名的请求不能使用本地模型。云端 systemd 服务明确设置 `STUDY_LOCAL_CODEX=0`；即使误设为 `1`，缺少私有接入时仍不可用。游客服务始终禁用这个入口。

`GET /local-models/status` 提供可用状态，未安装接入的环境显示“云端暂不可用”。`POST /question-pool/prepare` 可传 `engine: "deepseek"` 或预留的 `"codex_cli"`；不可用的本地模型请求返回 503，不创建任务、不切换付费 API。通用任务入口也执行同一检查。

Codex 调用使用已有 ChatGPT 登录，不提取或复制登录密钥；调用失败不会回退 DS。每个任务通过独立的调用上下文运行，其他老师、教学、解题任务保留原调用方式。CLI 的具体配置及使用说明保存在 Git 忽略的本地目录中。

## 老师调用

鸡的各阶段默认 `gpt-6-astra` / `medium`，设置页可以修改模型与推理强度。`backend.local_models.call_teacher` 只在本机接入已启用且请求未经过代理时，调用私有的 `backend.routine_codex.run_prompt`，复用 ChatGPT 登录、超时、取消与并发限制。注册普通用户、游客与云端不能使用本机登录额度；失败不会回退到付费 API。私有适配器仍留在 Git 忽略范围，合并代码时保留本机现有文件即可。
