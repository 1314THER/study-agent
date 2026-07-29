import json, os, re
from backend.solver import TEACHER_CONFIG, call_deepseek, step_solver_only, step_verify_all
from backend.database import find_question, save_question as db_save_question

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def _rp(n):
    with open(os.path.join(PROMPTS_DIR, f"{n}.md"), encoding="utf-8") as f:
        return f.read().strip()

TC = _rp("teach_check")
TF = _rp("teach_format")

def _ej(t):
    t = t.strip()
    m = re.search(r"```(\s*json)?\s*\n?(.*?)\n?```", t, re.DOTALL)
    if m:
        t = m.group(2) or m.group(1) or ""
        t = t.strip()
    for c, cl in [("[", "]"), ("{", "}")]:
        f = t.find(c)
        if f >= 0:
            t = t[f:]
            l = t.rfind(cl)
            if l >= 0:
                t = t[:l+1]
            break
    return t.strip()

def _bs(crr):
    r, ht = [], False
    for cr in crr:
        ct = cr.get("chunk_type", "整体")
        cn = cr.get("category", {}).get("level1", "")
        fa = cr.get("final_answer", "")
        for s in cr.get("steps", []):
            st = {"chunk_id": cr.get("chunk_id", 1)}
            st["chunk_type"] = ct
            st["category"] = cn
            st["step_number"] = s.get("step_number", 0)
            st["title"] = s.get("title", "")
            st["step_prompt"] = s.get("step_prompt", "")
            st["step_answer"] = s.get("step_answer", "")
            st["standard_writing"] = s.get("standard_writing", "")
            st["detailed_writing"] = s.get("detailed_writing", "")
            st["knowledge_point"] = s.get("knowledge_point", "")
            if st["step_prompt"]:
                ht = True
            r.append(st)
        if fa:
            r.append({"chunk_id": cr.get("chunk_id", 1), "chunk_type": ct,
                      "category": cn, "step_number": 999, "title": "\u6700\u7ec8\u7b54\u6848",
                      "step_prompt": "\u8bf7\u5199\u51fa\u8fd9\u9053\u9898\u7684\u6700\u7ec8\u7b54\u6848",
                      "step_answer": fa, "standard_writing": fa,
                      "detailed_writing": "", "knowledge_point": ""})
    return r, ht

def _fs(steps, teacher=None):
    tg = [s for s in steps if s["title"] != "\u6700\u7ec8\u7b54\u6848"]
    if not tg:
        return steps
    inp = [{"title": s["title"], "standard_writing": s["standard_writing"]} for s in tg]
    cfg = TEACHER_CONFIG.get(teacher or "liangliang", TEACHER_CONFIG["liangliang"])
    c, _ = call_deepseek(TF, json.dumps(inp, ensure_ascii=False, indent=2),
                         temperature=0.3,
                         model=cfg.get("verifier", {}).get("model", "deepseek-v4-flash"))
    try:
        rl = json.loads(_ej(c))
    except Exception:
        rl = []
    ns = []
    idx = 0
    for s in steps:
        ss = dict(s)
        if ss["title"] == "\u6700\u7ec8\u7b54\u6848":
            ss["step_prompt"] = "\u8bf7\u5199\u51fa\u8fd9\u9053\u9898\u7684\u6700\u7ec8\u7b54\u6848"
            ss["step_answer"] = ss["standard_writing"]
        else:
            if idx < len(rl):
                m = rl[idx]
                ss["step_prompt"] = m.get("step_prompt", ss.get("step_prompt", ""))
                ss["step_answer"] = m.get("step_answer", ss.get("step_answer", ""))
            idx += 1
        ns.append(ss)
    return ns

def _mg(cr, ts):
    si = 0
    for cr_ in cr:
        for s in cr_.get("steps", []):
            if si < len(ts):
                s["step_prompt"] = ts[si].get("step_prompt", "")
                s["step_answer"] = ts[si].get("step_answer", "")
                si += 1
    return cr

def teach_find_or_format(question, teacher=None):
    r = find_question(question)
    if not r or not r.get("chunk_results"):
        return {"found": False}
    cr = r["chunk_results"]
    steps, ht = _bs(cr)
    if not ht:
        steps = _fs(steps, teacher)
        cr = _mg(cr, steps)
        r["chunk_results"] = cr
        try:
            db_save_question(question, r)
        except Exception:
            pass
    fc = cr[0] if cr else {}
    cn = fc.get("category", {}).get("level1", "")
    return {"found": True, "question": question, "category": cn,
            "steps": steps, "total_steps": len(steps),
            "chunk_results": cr,
            "overall_difficulty": r.get("overall_difficulty"),
            "from_db": True}

def teach_start(question, teacher=None):
    sr = step_solver_only(question, teacher=teacher)
    if sr.get("error"):
        return sr
    vr = step_verify_all(sr["content"], question, sr.get("category"),
                         teacher=teacher)
    if vr.get("error"):
        return vr
    cr = vr["chunk_results"]
    steps, _ = _bs(cr)
    steps = _fs(steps, teacher)
    cr = _mg(cr, steps)
    aj = {"chunk_results": cr,
          "overall_difficulty": vr.get("overall_difficulty"),
          "knowledge_points": [], "final_answer": ""}
    for c in cr:
        if c.get("final_answer"):
            aj["final_answer"] += (" | " if aj["final_answer"] else "") + c["final_answer"]
        for kp in c.get("knowledge_points", []):
            if kp not in aj["knowledge_points"]:
                aj["knowledge_points"].append(kp)
    try:
        db_save_question(question, aj)
    except Exception:
        pass
    steps, _ = _bs(cr)
    return {"question": question, "category": sr.get("category"),
            "steps": steps, "total_steps": len(steps),
            "chunk_results": cr,
            "overall_difficulty": vr.get("overall_difficulty"),
            "from_db": False}

def teach_check(question, step_prompt, step_answer, user_answer, teacher=None):
    up = f"原题：{question}\n当前步骤引导问题：{step_prompt}\n参考答案：{step_answer}\n学生回答：{user_answer}"
    cfg = TEACHER_CONFIG.get(teacher or "liangliang", TEACHER_CONFIG["liangliang"])
    c, _ = call_deepseek(TC, up, temperature=0.2,
                         model=cfg.get("verifier", {}).get("model", "deepseek-v4-flash"))
    try:
        return json.loads(_ej(c))
    except Exception:
        return {"is_correct": False, "is_partial": False,
                "feedback": "抱歉，无法判断", "error_type": "其他", "error_detail": ""}

# ====== 对话式教学会话管理 ======

import uuid as _uuid
from typing import Optional, List, Dict, Any

# 读取新对话式 prompt
TChat = _rp("teach_chat")

class TeachSessionManager:
    """内存中的教学会话管理器（单用户，重启清空）"""

    def __init__(self):
        self._sessions: Dict[str, dict] = {}

    def create(self, question: str, teacher: str = None) -> dict:
        """创建新教学会话：解题 → 取步骤 → 存入 session"""
        # 先尝试从题库找
        from backend.database import find_question
        r = find_question(question)
        vr = None
        if r and r.get("chunk_results"):
            cr = r["chunk_results"]
        else:
            # 走完整解题流水线
            from backend.solver import step_solver_only, step_verify_all
            sr = step_solver_only(question, teacher=teacher)
            if sr.get("error"):
                return {"error": sr.get("error"), "detail": sr.get("detail", "")}
            vr = step_verify_all(sr["content"], question, sr.get("category"), teacher=teacher)
            if vr.get("error"):
                return {"error": vr.get("error"), "detail": vr.get("detail", "")}
            cr = vr["chunk_results"]
            # 入库
            aj = {"chunk_results": cr, "overall_difficulty": vr.get("overall_difficulty"),
                  "knowledge_points": [], "final_answer": ""}
            for c in cr:
                if c.get("final_answer"):
                    aj["final_answer"] += (" | " if aj["final_answer"] else "") + c["final_answer"]
                for kp in c.get("knowledge_points", []):
                    if kp not in aj["knowledge_points"]:
                        aj["knowledge_points"].append(kp)
            try:
                db_save_question(question, aj)
            except Exception:
                pass

        # 从 chunk_results 构建步骤列表（不含最终答案步骤）
        steps = []
        for cr_ in cr:
            ct = cr_.get("chunk_type", "整体")
            cn = cr_.get("category", {}).get("level1", "")
            fa = cr_.get("final_answer", "")
            for s in cr_.get("steps", []):
                steps.append({
                    "chunk_id": cr_.get("chunk_id", 1),
                    "chunk_type": ct,
                    "category": cn,
                    "step_number": s.get("step_number", 0),
                    "title": s.get("title", ""),
                    "standard_writing": s.get("standard_writing", ""),
                    "detailed_writing": s.get("detailed_writing", ""),
                    "knowledge_point": s.get("knowledge_point", ""),
                    "step_answer": s.get("step_answer", s.get("standard_writing", "")),
                })
            if fa:
                steps.append({
                    "chunk_id": cr_.get("chunk_id", 1),
                    "chunk_type": ct,
                    "category": cn,
                    "step_number": 999,
                    "title": "最终答案",
                    "standard_writing": fa,
                    "detailed_writing": "",
                    "knowledge_point": "",
                    "step_answer": fa,
                })

        session_id = str(_uuid.uuid4())
        self._sessions[session_id] = {
            "session_id": session_id,
            "question": question,
            "teacher": teacher or "liangliang",
            "steps": steps,
            "total_steps": len(steps),
            "current_step": 0,
            "step_introduced": False,   # 当前步骤是否已给过引导
            "attempt_count": 0,         # 当前步骤的回答次数
            "messages": [],             # [{role, content, step_index, ...}]
            "stats": {"correct": 0, "wrong": 0, "skipped": 0, "viewed_answer": 0},
            "step_results": [],         # 每步的最终记录 [{step_index, correct, attempts, ...}]
            "chunk_results": cr,
            "overall_difficulty": (r.get("overall_difficulty") if (r and r.get("chunk_results")) else (vr.get("overall_difficulty") if vr else None)),
        }
        return {"session_id": session_id, **self._sessions[session_id]}

    def get(self, session_id: str) -> Optional[dict]:
        return self._sessions.get(session_id)

    def add_message(self, session_id: str, role: str, content: str,
                    step_index: int = None, metadata: dict = None):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        msg = {"role": role, "content": content, "step_index": step_index or sess["current_step"]}
        if metadata:
            msg.update(metadata)
        sess["messages"].append(msg)

    def advance_step(self, session_id: str):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        sess["current_step"] += 1
        sess["step_introduced"] = False
        sess["attempt_count"] = 0

    def is_complete(self, session_id: str) -> bool:
        sess = self._sessions.get(session_id)
        return sess and sess["current_step"] >= sess["total_steps"]


# 全局会话管理器实例
_session_manager = TeachSessionManager()


def teach_session_start(question: str, teacher: str = None) -> dict:
    """对外：创建教学会话，返回会话信息和第一轮 AI 引导"""
    result = _session_manager.create(question, teacher)
    if result.get("error"):
        return result

    # 生成第一轮 AI 引导消息
    return _do_chat_turn(result["session_id"], None)


def _build_steps_reference(sess: dict) -> str:
    """把步骤列表格式化为 prompt 参考文本"""
    lines = []
    for i, s in enumerate(sess["steps"]):
        lines.append(f"步骤 {i+1}: {s.get('title', '')}")
        lines.append(f"  标准解答: {s.get('standard_writing', '')}")
        if s.get("knowledge_point"):
            lines.append(f"  知识点: {s.get('knowledge_point', '')}")
    return "\n".join(lines)


def _build_conversation_history(sess: dict, max_turns: int = 20) -> str:
    """构建对话历史文本（最近 N 轮）"""
    msgs = sess["messages"]
    # 只取最近 max_turns*2 条消息（师生各一算一轮）
    tail = msgs[-(max_turns * 2):]
    lines = []
    for m in tail:
        role_label = "老师" if m["role"] == "teacher" else "学生"
        lines.append(f"{role_label}：{m['content']}")
    return "\n".join(lines)


def _format_prompt(sess: dict, student_message: str = None) -> str:
    """组装对话式 prompt"""
    steps_ref = _build_steps_reference(sess)
    conv_hist = _build_conversation_history(sess)
    step = sess["steps"][sess["current_step"]] if sess["current_step"] < sess["total_steps"] else sess["steps"][-1]

    return TChat.format(
        question=sess["question"],
        steps_reference=steps_ref,
        current_step_index=sess["current_step"] + 1,
        total_steps=sess["total_steps"],
        current_step_title=step.get("title", ""),
        current_step_answer=step.get("step_answer", step.get("standard_writing", "")),
        step_introduced="是" if sess["step_introduced"] else "否",
        attempt_count=sess["attempt_count"],
        conversation_history=conv_hist if conv_hist else "(无)",
        student_message=student_message if student_message else "(这是第一轮，请先给出步骤引导)",
    )


def _do_chat_turn(session_id: str, student_message: str = None) -> dict:
    """执行一轮对话：组装 prompt → 调用 AI → 解析结果 → 更新 session"""
    sess = _session_manager.get(session_id)
    if not sess:
        return {"error": "session_not_found", "detail": "会话不存在"}

    # 检查是否已完成
    if sess["current_step"] >= sess["total_steps"]:
        return {"action": "complete", "message": "所有步骤已完成！", "session_id": session_id}

    # 记录学生消息
    if student_message:
        _session_manager.add_message(session_id, "student", student_message)
        sess["attempt_count"] += 1

    # 组装 prompt
    prompt = _format_prompt(sess, student_message)
    cfg = TEACHER_CONFIG.get(sess["teacher"], TEACHER_CONFIG["liangliang"])

    try:
        c, _ = call_deepseek(TChat, prompt, temperature=0.3,
                             model=cfg.get("verifier", {}).get("model", "deepseek-v4-flash"))
    except Exception as e:
        return {"error": "ai_error", "detail": f"AI 老师暂时无法响应: {str(e)[:100]}",
                "action": "error", "message": "抱歉，AI 老师暂时无法响应，请检查网络连接。",
                "session_id": session_id}

    try:
        result = json.loads(_ej(c))
    except Exception:
        result = {"action": "error", "message": "抱歉，我有点卡住了，能再说一遍吗？",
                  "is_correct": None, "error_type": None, "error_detail": None}

    action = result.get("action", "guide")
    msg = result.get("message", "")

    # 根据 action 更新 session
    if action in ("advance",):
        # 记录当前步骤结果
        sess["step_results"].append({
            "step_index": sess["current_step"],
            "correct": True,
            "attempts": sess["attempt_count"],
            "viewed_answer": False,
        })
        sess["stats"]["correct"] += 1
        _session_manager.add_message(session_id, "teacher", msg, metadata={
            "action": action, "is_correct": result.get("is_correct")})
        _session_manager.advance_step(session_id)
        # 如果还有下一步，自动生成下一步引导
        if sess["current_step"] < sess["total_steps"]:
            # 先做一次无学生消息的 chat turn 来生成下一步引导
            sess["step_introduced"] = True
            next_result = _do_chat_turn(session_id, None)
            # 合并结果：advance 消息 + 下一步引导
            return {
                "action": "advance",
                "message": msg,
                "next_step_message": next_result.get("message", ""),
                "current_step": sess["current_step"] + 1,
                "total_steps": sess["total_steps"],
                "session_id": session_id,
            }
        else:
            return {
                "action": "complete",
                "message": "🎉 你完成了所有步骤！",
                "session_id": session_id,
                "stats": sess["stats"],
                "step_results": sess["step_results"],
            }

    elif action in ("show_answer",):
        sess["stats"]["viewed_answer"] += 1
        sess["step_results"].append({
            "step_index": sess["current_step"],
            "correct": False,
            "attempts": sess["attempt_count"],
            "viewed_answer": True,
        })
        _session_manager.add_message(session_id, "teacher", msg, metadata={
            "action": action})
        # 标记已展示答案，后续让学生重试

    elif action == "complete":
        # 直接完成
        pass

    else:  # guide / error
        if action == "guide":
            sess["step_introduced"] = True
        _session_manager.add_message(session_id, "teacher", msg, metadata={
            "action": action,
            "is_correct": result.get("is_correct"),
            "error_type": result.get("error_type"),
            "error_detail": result.get("error_detail"),
        })

    return {
        "action": result.get("action", "guide"),
        "message": msg,
        "is_correct": result.get("is_correct"),
        "error_type": result.get("error_type"),
        "error_detail": result.get("error_detail"),
        "current_step": sess["current_step"] + 1,
        "total_steps": sess["total_steps"],
        "session_id": session_id,
        "stats": sess["stats"],
        "step_results": sess["step_results"],
    }


def teach_session_chat(session_id: str, student_message: str) -> dict:
    """对外：发送学生消息，返回 AI 回应"""
    return _do_chat_turn(session_id, student_message)


def teach_get_session(session_id: str) -> Optional[dict]:
    """对外：获取会话完整信息"""
    sess = _session_manager.get(session_id)
    if not sess:
        return None
    return {
        "session_id": sess["session_id"],
        "question": sess["question"],
        "teacher": sess["teacher"],
        "current_step": sess["current_step"],
        "total_steps": sess["total_steps"],
        "messages": sess["messages"],
        "stats": sess["stats"],
        "step_results": sess["step_results"],
        "overall_difficulty": sess.get("overall_difficulty"),
    }
