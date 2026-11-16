/* Public explanation fixtures. Planned objects are not recorded backend runs. */
window.WENXIA_DEMO = {
  "phases": [
    {
      "id": "input",
      "label": "输入保存",
      "nodes": [
        "clients",
        "gateway",
        "db2",
        "agent"
      ],
      "edges": [
        "request",
        "task",
        "save"
      ],
      "owner": "采集端与领域服务",
      "input": "题目、原始作答、身份与课程版本",
      "action": "保存原图/文本及修订，绑定任务范围；CLEAN 只做保真识别。",
      "output": "asset_ref、AttemptRevision、TaskContract",
      "rw": "W DB2：原始材料引用、作答版本；媒体进入受控资产存储。"
    },
    {
      "id": "evidence",
      "label": "检索与上下文",
      "nodes": [
        "agent",
        "db1",
        "db2",
        "db3"
      ],
      "edges": [
        "rag1",
        "rag2",
        "state"
      ],
      "owner": "Retriever 与 Context Compiler",
      "input": "当前任务、课程约束、题目与作答",
      "action": "RAG1 查教学依据，RAG2 查相关事实，再读 DB3；保留引用与冲突证据。",
      "output": "EvidenceBundle、ContextManifest",
      "rw": "R DB1 / DB2 / DB3；派生检索索引不作为事实来源。"
    },
    {
      "id": "reason",
      "label": "推理与工具执行",
      "nodes": [
        "agent",
        "model",
        "tools"
      ],
      "edges": [
        "model",
        "action"
      ],
      "owner": "Agent 与本地模型的逻辑角色",
      "input": "角色规则、证据包、允许工具与预算",
      "action": "模型提出动作，服务核验工具参数；执行后观察真实返回，按需补查或停止。",
      "output": "ActionProposal、ToolResult、GradeDraft",
      "rw": "按授权工具读库；此时模型提案尚不是正式评分。"
    },
    {
      "id": "commit",
      "label": "核验与提交",
      "nodes": [
        "tools",
        "gateway",
        "db2"
      ],
      "edges": [
        "write"
      ],
      "owner": "领域服务与事务边界",
      "input": "提案、引用、对象版本、数学/教学检查结果",
      "action": "检查权限、引用、量规、当前版本与幂等键，再在同一事务保存结果和事件。",
      "output": "GradeRevision、outbox 事件、提交回执",
      "rw": "W DB2：正式评分/反馈修订与事件；保留旧版本。"
    },
    {
      "id": "feedback",
      "label": "反馈与帮助记录",
      "nodes": [
        "clients",
        "gateway",
        "db2"
      ],
      "edges": [
        "feedback",
        "save"
      ],
      "owner": "教学服务与客户端",
      "input": "已经提交的反馈、分级提示与展示确认",
      "action": "向学生展示反馈；记录实际帮助暴露与辅助订正，不直接据此判定独立掌握。",
      "output": "TutorTurn、HintExposed、辅助作答修订",
      "rw": "W DB2：帮助条件、展示确认及新作答事实。"
    },
    {
      "id": "revision",
      "label": "学情修订",
      "nodes": [
        "events",
        "model",
        "db2",
        "db3",
        "db1",
        "agent"
      ],
      "edges": [
        "event",
        "semantic",
        "patch",
        "rag1",
        "rag2",
        "state"
      ],
      "owner": "事件消费者、TA 与受控修订服务",
      "input": "正式事件、旧学情与重新检索的相关证据",
      "action": "LLM 提出新增、收窄或撤回的 WikiPatch；服务核对引用和 base_revision 后保存。",
      "output": "有证据的新 StateRevision、受影响任务",
      "rw": "R DB1 / DB2 / DB3；W DB3 新版本，记录处理位点。"
    },
    {
      "id": "verify",
      "label": "任务与独立验证",
      "nodes": [
        "clients",
        "agent",
        "db1",
        "db2",
        "db3",
        "gateway"
      ],
      "edges": [
        "rag1",
        "rag2",
        "state",
        "request",
        "feedback",
        "save"
      ],
      "owner": "任务规划器、学生与教师",
      "input": "当前学情、未验证项、课程目标与帮助历史",
      "action": "排除已暴露题目，安排无提示新题及延迟复测；教师纠错可触发重新判断。",
      "output": "新任务、独立表现、下一轮证据",
      "rw": "R 三库；W DB2 新事实，后续事件再维护 DB3。"
    }
  ],
  "traces": {
    "normal": {
      "label": "正常执行",
      "intro": "以同一道三角形题的错误作答说明拟议批改协议；对象版本均为示意。",
      "steps": [
        {
          "state": "received",
          "action": "绑定题目与作答修订",
          "tool": "save_attempt → attempt:demo-r1",
          "check": "原始 C=π/3 保留，未替学生改写",
          "next": "retrieve",
          "phase": 0
        },
        {
          "state": "retrieve",
          "action": "查内角和、已发布解法与已有帮助",
          "tool": "retrieve_evidence → E1 / E2 / E3",
          "check": "来源、课程版本和学生范围一致",
          "next": "compile",
          "phase": 1
        },
        {
          "state": "compile",
          "action": "组织 GRADER 上下文",
          "tool": "compile_context → manifest:demo-1",
          "check": "原答、量规、未知与允许工具分别标识",
          "next": "propose",
          "phase": 2
        },
        {
          "state": "propose",
          "action": "提出首错诊断",
          "tool": "SOCRATIC.GRADER → GradeDraft",
          "check": "指出 4C=π，因此 C 应为 π/4；原因仍待核",
          "next": "validate_action",
          "phase": 3
        },
        {
          "state": "validate_action",
          "action": "检查动作与依据",
          "tool": "validate_draft → valid",
          "check": "引用能定位原文；未给出未经确认的考试分数",
          "next": "execute",
          "phase": 4
        },
        {
          "state": "execute",
          "action": "调用受控评分提交工具",
          "tool": "commit_grade → grade:demo-r1",
          "check": "服务再次核对 attempt_revision 和幂等键",
          "next": "observe",
          "phase": 5
        },
        {
          "state": "observe",
          "action": "核对实际提交回执",
          "tool": "receipt → grade:demo-r1 / event:demo-1",
          "check": "回执存在；重试应返回相同修订",
          "next": "commit / stop",
          "phase": 6
        },
        {
          "state": "completed",
          "action": "返回正式诊断并等待下一次作答",
          "tool": "已保存 GradeRevision；outbox 等待消费",
          "check": "本任务结束，独立掌握仍未知",
          "next": "waiting_student",
          "phase": 7
        }
      ]
    },
    "missing": {
      "label": "证据不足",
      "intro": "演示关键输入缺失时怎样等待澄清；不把缺失材料补成模型猜测。",
      "steps": [
        {
          "state": "received",
          "action": "保存可辨认的部分作答",
          "tool": "save_attempt → partial_input",
          "check": "关键角度符号存在歧义",
          "next": "retrieve",
          "phase": 0
        },
        {
          "state": "retrieve",
          "action": "查找能核对歧义的证据",
          "tool": "retrieve_asset → insufficient",
          "check": "原图和历史都不能确认该符号",
          "next": "observe",
          "phase": 1
        },
        {
          "state": "observe",
          "action": "检查当前证据是否足够",
          "tool": "evidence_check → needs_clarification",
          "check": "无法确定原答写的是 π/3 还是其他值",
          "next": "waiting_input",
          "phase": 6
        },
        {
          "state": "waiting_input",
          "action": "向学生请求确认原始符号",
          "tool": "clarification_request → 待答",
          "check": "不提交确定错因、不更新掌握状态",
          "next": "学生补充后重新取证",
          "phase": 7
        }
      ]
    },
    "correction": {
      "label": "教师纠错",
      "intro": "演示教师补充证据后，旧评分和旧学情怎样被新修订替代；并非这份实录已发生的事件。",
      "steps": [
        {
          "state": "received",
          "action": "接收教师复核及原稿位置",
          "tool": "TeacherReview → review:demo-1",
          "check": "复核绑定原评分版本和作答版本",
          "next": "retrieve",
          "phase": 0
        },
        {
          "state": "retrieve",
          "action": "重读原图、旧诊断和教师证据",
          "tool": "EvidenceBundle → corrected_evidence",
          "check": "发现旧转写遗漏了一个正确步骤",
          "next": "compile",
          "phase": 1
        },
        {
          "state": "compile",
          "action": "组织含反证的复核上下文",
          "tool": "ContextManifest → review_context",
          "check": "旧结论与新证据同时保留",
          "next": "propose",
          "phase": 2
        },
        {
          "state": "propose",
          "action": "提出撤回旧结论的修订",
          "tool": "GradeDraft → supersedes demo-r1",
          "check": "改的是诊断依据，原始记录仍保留",
          "next": "validate_action",
          "phase": 3
        },
        {
          "state": "validate_action",
          "action": "核验权限、引用和旧版本",
          "tool": "validate_revision → valid",
          "check": "教师可复核该班；base_revision 尚有效",
          "next": "execute",
          "phase": 4
        },
        {
          "state": "execute",
          "action": "追加新评分和替代事件",
          "tool": "GradeRevision demo-r2 + GradeSuperseded",
          "check": "事务保存；幂等键防止重复修订",
          "next": "observe",
          "phase": 5
        },
        {
          "state": "observe",
          "action": "事件消费者重新核对学情依据",
          "tool": "TA → WikiPatch 撤回失去支持的判断",
          "check": "base_revision 冲突时重新取证",
          "next": "commit / stop",
          "phase": 6
        },
        {
          "state": "completed",
          "action": "保存 DB3 新版本并刷新受影响任务",
          "tool": "StateRevision demo-r4；班级视图重算",
          "check": "事件处理位点前进，旧版本仍可查",
          "next": "等待后续独立证据",
          "phase": 7
        }
      ]
    }
  },
  "evidence": [
    {
      "id": "db1",
      "code": "E1",
      "title": "教学依据",
      "type": "DB1 · SQLite / FTS5",
      "source": "原题条件与已有解析；映射为拟议教学对象",
      "record": "release: demo-course-r1\nrelation: 内角和 + A+B=3C\nstep: 4C=π → C=π/4\nreview_state: 需随实际发布集核对",
      "context": "[E1 教学依据] 由 A+B+C=π 与 A+B=3C 可得 4C=π；当前步骤应得到 C=π/4。",
      "meaning": "数据库保存可引用的步骤与适用条件，FTS5、公式和语义检索只召回候选。"
    },
    {
      "id": "db2",
      "code": "E2",
      "title": "作答与帮助事实",
      "type": "DB2 · PostgreSQL / JSONB",
      "source": "已保存构造作答的原文；对象与版本为协议示意",
      "record": "attempt_revision: demo-attempt-r1\nasset_ref: demo-original\nstudent_text: 由 A+B=3C 和 A+B+C=π，得 C=π/3。于是 B=2π/3-A。代入 2sin(A-C)=sinB，展开得 sinA-√3cosA=(sinA+√3cosA)/2，所以 tanA=3√3，sinA=3√21/14。\nhelp_exposure: 无法从此独立批改记录推定",
      "context": "[E2 作答事实] 学生原文写“得 C=π/3”，后续沿用了这个值。与教学五帧记录是独立录制。",
      "meaning": "关系表约束对象与版本，JSONB 承载扩展载荷；媒体保存为受控 asset_ref。"
    },
    {
      "id": "db3",
      "code": "E3",
      "title": "当前学情",
      "type": "DB3 · Wiki / PostgreSQL 修订",
      "source": "基于同题的拟议状态样本；不是已有学生档案",
      "record": "state_revision: demo-state-r3\nclaim: 本次求角 C 的推导需核对\ncertainty: 错误可定位，原因待核\nevidence_refs: [E1, E2]\nindependent_mastery: unknown",
      "context": "[E3 当前判断] 仅能定位本次错误；没有无提示新题证据，不推断长期不会或已经掌握。",
      "meaning": "Wiki 保存可读解释，PG 保存 revision、base_revision、证据与同步位点，支持反证和撤回。"
    }
  ],
  "tasks": [
    {
      "id": "A",
      "title": "解题与课程适配",
      "initial": "题目、课程发布版本与允许方法",
      "visible": "原题、已授权教学依据、数学工具",
      "target": "得到正确答案和可核对推理，接受合理异解",
      "failure": "关键结论错误、超出课程约束、引用不存在",
      "cost": "每次合格解答成本；时延、token、必要复核"
    },
    {
      "id": "B",
      "title": "批改与诊断",
      "initial": "本题 C=π/3 的原始作答与量规",
      "visible": "题目、作答、同等参考资料和帮助条件",
      "target": "定位首错，区分连带错误，证据不足保留未知",
      "failure": "错判正确异解、无依据归因、编造考试分数",
      "cost": "每份合格诊断成本；重大误判与教师复核时间"
    },
    {
      "id": "C",
      "title": "出题、组卷与评卷",
      "initial": "课程目标、题库版本、覆盖与时长约束",
      "visible": "授权候选题、方法边界、组卷工具",
      "target": "形成有效题目/试卷及可解释的覆盖结果",
      "failure": "题目无解、泄露答案、覆盖或时长约束失败",
      "cost": "每个有效候选/合格试卷成本与校验次数"
    },
    {
      "id": "D",
      "title": "教学引导与训练选择",
      "initial": "当前错误、提示等级与学习目标",
      "visible": "已公开给学生的内容、授权证据与工具",
      "target": "给出适量帮助，保留思考空间并选择相关训练",
      "failure": "泄露完整答案、无关补练、把帮助后完成当独立掌握",
      "cost": "有效提示成本、提示依赖与教师评价"
    },
    {
      "id": "E",
      "title": "学情、记忆与修订",
      "initial": "旧状态、作答/帮助事件、教师反证",
      "visible": "当前事件与允许读取的历史事实",
      "target": "有引用地新增、收窄或撤回判断，幂等处理事件",
      "failure": "重复计数、迟到事件丢失、反证未传播、版本被覆盖",
      "cost": "每次正确修订成本、恢复时延与冲突次数"
    },
    {
      "id": "F",
      "title": "任务与复习规划",
      "initial": "目标、截止时间、时间预算和学习状态",
      "visible": "任务约束、已观测状态与可用练习",
      "target": "给出满足约束的可执行安排，并解释取舍",
      "failure": "超出时间预算、遗漏必做事项、使用未授权数据",
      "cost": "合格规划成本、冲突解决与后续修订次数"
    },
    {
      "id": "G",
      "title": "无历史与自然接续",
      "initial": "无历史、零散导入或中途入组的初态",
      "visible": "已授权材料、实际观察窗口、可选短测",
      "target": "保留未知，支持直接使用或测试，按时间接续",
      "failure": "把未考查当不会、把缺材料记零分、重复导入计数",
      "cost": "首次有效帮助时间、额外交互与导入复核成本"
    },
    {
      "id": "H",
      "title": "教师协作",
      "initial": "班级任务、作答、复核与未观测名单",
      "visible": "教师授权范围内的课程、量规和原始证据",
      "target": "形成可下钻班级报告，纠错传播到后续任务",
      "failure": "分母错误、越权查看、纠错未传播、净负担增加",
      "cost": "同质量下备课、阅读、复核和修正总时间"
    }
  ],
  "lora": [
    {
      "title": "业务记录",
      "body": "保留原始输入、实际输出和失败。下面来自本题教学记录的第三帧，不能直接当成高质量监督目标。",
      "sample": "给你一点提示：$C=\\frac{\\pi}{4},\\ \\tan\n\n再想想看？"
    },
    {
      "title": "人工校准",
      "body": "拟议审核流程：接受、修改或拒绝分别记录。不完整提示应进入审核队列，不能把自动修补当成真实教师确认。",
      "sample": "review_state: pending\npossible_decision: reject_or_revise\nreason: 提示不完整，需人工确认教学目标与目标输出\nreviewer / diff / evidence: 待实际审核"
    },
    {
      "title": "训练样本",
      "body": "只从通过审核的记录构造角色条件化样本；题族、学生和事件链先隔离，再训练。以下为字段结构示意。",
      "sample": "role: SOCRATIC.TUTOR\ninput: 题目 + 当前作答 + 帮助等级 + 证据引用\ntarget: 经人工确认的反馈与工具动作\nreview_state: accepted 才可进入 train\nsplit: train / dev / sealed（独立冻结）"
    },
    {
      "title": "固定任务验证",
      "body": "固定数据库、上下文和工具协议，比较基座与 LoRA。封存任务报告完整业务质量、失败与资源，不使用训练集表现代替。",
      "sample": "对照：约 9B 基座 / 约 9B LoRA / 强系统\n其他档位：4B / 27B\n验收：任务结果 + 引用 + 状态 + 副作用 + 成本\nresults: 待测"
    }
  ],
  "source": {
    "case": "propagation",
    "example": "national-2023-q17",
    "teacher": "liangliang"
  }
};
