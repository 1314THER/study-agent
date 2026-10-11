# 解析预制几何演示

新解析在 Formatter 最终校验成功后预制几何数据，再与文字一起返回、保存。前端不调用模型画图，不运行模型输出的脚本。解析校验失败、预制超时或构型无法确定时，保留文字与可访问的原题图。

## 数据

answer_json 新增可选 geometry 和 asset_refs，不需要迁移数据库。geometry 的 version 为 1，status 为 ready、partial 或 unavailable，含 source_hash、reason、scenes、steps、issues。

场景包含 dimension、bounds、objects，以及可选的 parameter 和预计算 frames。步骤以 chunk_id-step_number 为唯一键，例如 1-2；多问中的“步骤1”各自独立。

~~~json
{
  "step_key": "1-2",
  "scene_id": "main",
  "full_visible": ["E", "PE", "CE"],
  "hint_groups": [
    {"text": "取AB中点E，连接PE。", "visible": ["E", "PE"], "highlight": ["PE"]},
    {"text": "连接CE，建立下一条垂直关系。", "visible": ["CE"], "highlight": ["CE"]}
  ]
}
~~~

base:true 用于题设图形；辅助对象的 introduced_at 声明首次所属步骤，校验器拦截提前引用。AI 根据当前步骤难度和构造依赖决定提示颗粒度。文字与绘图动作按组对应，简单构造可以一次展示，困难构造分组。

后台验证引用、坐标、半径、共面性、非退化圆锥曲线、平行/垂直/夹角、长度、点的归属、切线、定点、定长和以及轨迹采样的曲线方程。校验条件须有题干或解析中的原文依据。失败最多修复一次，保留独立通过校验的场景与步骤，否则保存不可用原因。

支持点、直线、线段、向量、面、多边形、多面体、圆、球、圆柱、圆锥、圆锥曲线、角和轨迹采样。点构造支持中点、比例分点、投影、二维直线交点、平面投影及绕轴旋转。

坐标表达式只允许有长度、节点和数值边界的算术 AST 与数学函数，没有 eval。一个参数场景使用约61个采样位置，另包含初始值；后台逐帧计算、校验并保存数值，前端仅播放保存的帧，可用于截面、折叠和动点。

ready 表示声明的数据及关系可用，不代表自动认证了数学证明，也不保证 AI 已抽取全部题设条件。逐帧校验不等于证明连续区间的代数恒等式。

## 播放与教学

单题页、多模态结果、个人题库详情和原题池详情共用 geometry.js。可点击解析步骤、上一步、下一步、重播；二维平移缩放，三维旋转缩放，手机默认折叠。

教学 API 和持久化会话保留 geometry、asset_refs、geometry_state。进度示例：

~~~json
{"released":{"1-2":1},"completed":["1-1"]}
~~~

初始只显示题设图形。请求提示在原有教学事务内释放当前步骤下一组构造，并返回配套文字，不调用模型。看答案、答对或跳过完成本步构造，下一步等待提示。刷新直接恢复已完成动作，新增提示或主动重播才播放动作。教学结束在总结页回看全部演示。

沿用后台任务去重和会话版本控制；直接教学 chat API 也接受 expected_revision，过期请求返回 HTTP 409。步骤转换保留难度与几何键，保存教学结果保留完整几何数据。

旧几何题进入教学前按需补制，不重新解题、不批量回填。题干、解析文本、题图变化使来源摘要失效；只更新评分不使摘要失效。

## 题图与部署

PDF 切题保留对应整页图，图片切题保留规范化原图；上传临时文件清理不删除题图。尚未按单题精确裁剪，一页多题时预览可能显示整页。

素材位于用户工作区 question-assets/，前端只拿内容摘要编号，通过 /question-assets/{id} 读取；跨工作区不能访问。原题池只读取已留存的图片附件或所在 PDF 页，不改来源文件、候选状态或入库记录。缺失原图不根据图形外观猜条件；不自动下载远程图片。

静态站点须部署整个 vendor 目录：JSXGraph **1.11.1**、Three.js **0.180.0**，都按 MIT 许可保留许可文件。OrbitControls 的模块引用改为站内相对路径，不依赖 CDN。Python 沿用 requirements.txt 中的 Pillow、PyMuPDF。

来源及文件摘要：[geometry-manifest.json](../frontend/vendor/geometry-manifest.json)。参考 [JSXGraph 圆锥曲线文档](https://jsxgraph.org/docs/Conic.html)、[Three.js 文档](https://threejs.org/docs/) 与 [edulab 步骤模板](https://github.com/wy51ai/edulab/blob/master/skills/edu-solid-geometry/template/lesson.html)；没有复制 edulab 代码。

## 验证及限制

tests/geometry_cases.py 使用本地 highmath 原题中的椭圆焦点三角形、等边底面三棱锥体积作为模型与播放样例。其余是明确条件的构造测试，不能算真实题自动生成覆盖率。

| 样例 | 结果 |
| --- | --- |
| 椭圆焦半径 | 完整支持，分组连接两条焦半径 |
| 三棱锥中点与垂线 | 完整支持，分组显示 E、PE、CE |
| 正方体平行截面 | 数值帧、平行关系和参数播放通过 |
| 三角形绕轴折叠 | 数值帧、定长关系和参数播放通过 |
| 椭圆动点及轨迹 | 逐帧归属、轨迹采样方程通过 |
| 切线、定点和定长和 | 数值校验通过 |
| 错误关系、退化曲线、缺失引用 | 不可用，保留文字 |
| 有效场景加错误场景 | 部分支持，保留有效场景 |
| 条件不足/图缺失 | 模拟预制明确降级 |

~~~sh
python3 -m unittest tests.test_geometry -v
node tests/frontend_geometry.test.mjs
GEOMETRY_PYTHON=python3 CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" node tests/e2e/geometry_smoke.mjs
~~~

浏览器测试需要 Playwright，使用独立随机端口、自动创建并销毁临时数据库，模型全部模拟，不访问现有8000服务、不产生AI费用。验证实际二维/三维渲染、提示、答案、并发版本冲突、跳过、刷新、结束回看和手机画板。截图写入临时目录，可用 GEOMETRY_SHOTS 指定。

尚未调用真实模型进行大量题目的端到端生成评测；自动生成成功率、条件抽取完整性与提示粒度仍需真实样本验证。本次未重启现有服务、运行生产迁移或批量补制，也未修改正在入库的数据。
