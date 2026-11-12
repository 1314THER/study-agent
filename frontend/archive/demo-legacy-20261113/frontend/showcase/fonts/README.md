# 仿手写网页字体

本目录只为构造作答与教学中的学生输入提供仿手写排版。字体不能证明这些文字来自真实学生手写；页面应继续保留构造输入与固定录制的说明。

- CSS family：`StudyAgent Handwriting`
- 文件：`studyagent-handwriting.woff2`
- 字重与样式：400 / normal
- 上游：LXGW WenKai TC Regular，字体内部版本 1.330 / Google Fonts v11
- 官方仓库：https://github.com/lxgw/LxgwWenkaiTC
- 官方字体文件：https://fonts.gstatic.com/s/lxgwwenkaitc/v11/w8gDH20td8wNsI3f40DmtXZb48uK.ttf
- 官方许可：https://github.com/google/fonts/blob/main/ofl/lxgwwenkaitc/OFL.txt
- 字体直接取自 Google Fonts 的公开固定资源；许可通过 jsDelivr 读取官方 google/fonts 仓库。字体、原始许可与分发许可的 SHA-256 均在 coverage.json 中记录；分发文本只统一行尾空白。
- 授权：SIL Open Font License 1.1，完整原文见 `OFL.txt`。

此文件是重新命名的网页子集，保留上游版权与许可元数据。派生字体主名称使用 `StudyAgent Handwriting`，不使用上游保留字体名作为本字体的主名称。不分发原始 TTF、苹果系统字体或安装工具。

字符范围来自 `recordings.json` 六项 `student_answer`、全部 `teaching.frames[].input` 和开屏构造作答；另保留 ASCII、常用标点和数学字符。实际覆盖码位、原始字体摘要、结果摘要和字节数见 `coverage.json`。该子集不适合用于任意中文输入，新增示例应先重建并检查覆盖。

## 重建

构建依赖仅需在临时环境安装，不加入服务端运行依赖：

```bash
python3 -m pip install --target /tmp/study-agent-font-build/python 'fonttools[woff]'
PYTHONPATH=/tmp/study-agent-font-build/python python3 frontend/showcase/fonts/build_subset.py \
  --source /tmp/study-agent-font-build/LXGWWenKaiTC-Regular.ttf \
  --license /tmp/study-agent-font-build/OFL-TC.txt
```

构建器会检查所有目标字符均有真实字形，重命名字体家族，输出 WOFF2，再重新打开结果核验字符映射。输入文件应从上述上游资源下载。源字体和构建包均不随站点发布。
