# AI学习伴侣

面向高中生的AI学习陪伴系统。搜题做题 + 手把手教学 + 智能刷题 + 录屏分析。

---

## 工程进度

### ✅ 已完成

| 版本 | 内容 |
|------|------|
| **V0.1** | 做题系统基础版 — 三段式AI处理（Solver → Verifier → Formatter），输入题目返回结构化分步答案 |
| **V0.2** | 单用户小题库 — SQLite 数据库缓存题目，同题复用，秒出结果 |
| **知识分类** | 11个一级知识点分类 + 二级细分，固定列表由 AI 选择，储存在独立字段 |
| **难度评级** | 6维度评分（常规程度、步骤复杂度、交叉板块、计算量、理解难度、分类讨论），各0-2分，总分0-12 |
| **前端页面** | 搜题做题页面，显示解题步骤、分类标签、难度等级 |

### 📋 待完成

| 优先级 | 内容 | 说明 |
|--------|------|------|
| **P0** | 三段 Skill 定制 | `prompts/solver.md`、`verifier.md`、`formatter.md` 尚为初始模板，需改写为专属 skill |
| **P0** | 分类字典调整 | `backend/categories.py` 中的分类列表需进一步调整 |
| **P1** | V0.3 手把手教学 | 分步互动教学，学生输入 → AI 比对反馈 → 错因分类 |
| **P1** | V0.4 智能刷题 | AI 出题 → 学生作答 → AI 批改 → 练习报告 |
| **P1** | V0.5 系统集成 | 首页入口、各系统间跳转、学习记录沉淀 |
| **P2** | V1.0 录屏分析 | 上传录屏 → 拆帧 → OCR → 标准答案对比 → 分析报告 |

---

## 项目结构

```
study-agent/
├── backend/
│   ├── main.py              # FastAPI 服务器，接口定义
│   ├── solver.py            # 做题系统核心（三段式解题）
│   ├── database.py          # SQLite 小题库
│   ├── categories.py        # 知识点分类列表（可调整）
│   ├── prompts/
│   │   ├── solver.md        # Solver 提示词（待定制）
│   │   ├── verifier.md      # Verifier 提示词（待定制）
│   │   └── formatter.md     # Formatter 提示词（含难度评级）
│   └── __init__.py
├── frontend/
│   └── index.html           # 搜题做题页面
├── requirements.txt          # Python 依赖
├── .env                      # API Key（不提交）
├── .gitignore
└── README.md
```

---

## 数据库结构（questions 表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 自增主键 |
| `content` | TEXT | 题目原文（唯一） |
| `answer_json` | TEXT | 完整结构化答案（JSON） |
| `category_level1` | TEXT | 一级知识点分类（固定列表） |
| `category_level2` | TEXT | 二级知识点分类（固定列表） |
| `difficulty_level` | TEXT | 容易/中等/困难/极难 |
| `difficulty_score` | INTEGER | 总分 0-12 |
| `difficulty_dimensions` | TEXT | 六维度得分（JSON） |
| `common_mistakes` | TEXT | 常见错误（JSON） |
| `knowledge_points` | TEXT | 知识点列表（JSON） |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

---

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/solve` | 搜题，返回结构化答案（含 category、difficulty、steps） |
| GET | `/questions` | 查看历史题目 |
| GET | `/categories` | 获取知识点分类列表 |

---

## 启动

```bash
cd study-agent
pip install -r requirements.txt
uvicorn backend.main:app
```

后端运行在 http://127.0.0.1:8000。打开 `frontend/index.html` 即可使用。
