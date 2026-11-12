# 问侠评审展示站（独立前端）

本目录是为申请书评委准备的纯静态、只读项目说明站。页面围绕总体数据流、数据库与 LLM 协议、Agent Loop、完整学生作答场景、长期学习 / 班级教学、LoRA、Benchmark、部署和研究边界组织。站点不接收作答，不访问私有学习库，不调用模型 API。

## 本地预览

从仓库根目录运行：

```bash
python3 -m http.server 8303 --directory frontend
```

打开 `http://127.0.0.1:8303/wenxia-demo/index.html`。页面的样式、交互脚本和架构 SVG 均在本目录；无构建依赖。

## 发布接入

目标入口为 `https://demo.150.chat/`。现有 `backend.showcase:app` 仍负责只读静态资源白名单和部署排空 / 健康检查。发布时把 `/`、`/home.html` 映射至本目录的 `index.html`，并将本目录的 CSS、JS、favicon 和三张 SVG 图逐项加入公开白名单；旧版 `frontend/showcase` 与其资源不删除，方便独立回滚或后续迁站。

旧版 demo 的完整站点快照位于 `frontend/archive/demo-legacy-20261113/`，含旧前端公开白名单资源、旧静态服务模块和逐文件 SHA-256 清单。快照不覆盖现有 `demo.150.chat` 或 `math.150.chat`。

## 内容状态

- **已有基础**：当前仓库可查代码或模型实录。
- **拟议设计**：按申请书路线计划实现；不表示已经部署。
- **待验证**：需要封存 Benchmark 或获许可的真实使用来判断。

pgvector 是拟议选型；向量索引、三库语义维护、4B / 9B / 27B 新 LoRA 和本文 Benchmark 结果均未宣称已经落地。
