# DeepSeek 图片识别配置

系统的解题、校验、教学、批改、切题和手写识别统一使用 DeepSeek。账号只需一把 DeepSeek API Key。普通账号密钥在中央账户库中加密保存，不写入个人 `settings.json`，不继承游客共享密钥或主人的环境变量。

`api.deepseek` 配置包含 `base_url`、`vision_model` 和密钥状态。图片模型默认为 `deepseek-flash`，独立于各老师的文字模型配置。注册账号的请求使用服务端指定的 DeepSeek 官方地址，避免密钥被发送到用户自选的地址。主人可以保留现有文字老师的 Pro 配置。

现有配置加载后会删除 DashScope 字段，并把旧 Flash 模型名更新为 `deepseek-flash`。下一次保存设置时，删除结果会落盘；旧 DashScope 密钥不会转给 DeepSeek 或复制到其他工作区。部署游客 AI 快照时只导出 DeepSeek 配置。

## 文件与图片流程

- PDF 按页渲染并依次识别，不把整份 PDF 的图片同时堆入内存。
- JPG/PNG 在本地按 EXIF 纠正相机方向，转成 PNG，保持全图和长宽比，超出 8192 像素的长边等比缩小。
- Word/TXT 仍先提取文字，再调用同一个 DeepSeek 入口。
- 图片经 Chat Completions 的 `user.content[].image_url` 内联 data URL 传入；`detail=original`，识别调用关闭思考模式。
- 单张内联图片不得超过 32 MiB，请求体不得超过 48 MiB。超过输出长度的结果会报错，避免把截断的题目作为完整识别结果。

DeepSeek 仍会在模型内部按图片面积进行缩放，所以整页非常密集的小字可能丢失细节。上传清晰且摆正的图片，密集页面可按题目分开上传。本地流程不会自动裁掉图片中的题目。

## 官方参考

以下接口和限制于 2026-10-09 核验：

- [图像理解](https://api-docs.deepseek.com/zh-cn/guides/vision/)
- [模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
- [思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)
- [Responses API 图片格式](https://api-docs.deepseek.com/zh-cn/guides/responses_api/)

DeepSeek 官方已说明 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 由当前 Flash 模型承接，新配置使用 `deepseek-flash`。注册教程入口应链接官方 [DeepSeek 开放平台](https://platform.deepseek.com/)；登录、创建密钥和账户余额以开放平台实际界面为准。
