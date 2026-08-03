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
    fa_list = []
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
            fa_list.append({"chunk_id": cr.get("chunk_id", 1), "chunk_type": ct,
                      "category": cn, "step_number": 999, "title": "\u6700\u7ec8\u7b54\u6848",
                      "step_prompt": "\u8bf7\u5199\u51fa\u8fd9\u9053\u9898\u7684\u6700\u7ec8\u7b54\u6848",
                      "step_answer": fa, "standard_writing": fa,
                      "detailed_writing": "", "knowledge_point": ""})
    r.extend(fa_list)
    return r, ht

def _fs(steps, teacher=None):
    tg = [s for s in steps if s["title"] != "\u6700\u7ec8\u7b54\u6848"]
    if not tg:
        return steps
    inp = [{
        "chunk_id": s.get("chunk_id"),
        "step_number": s.get("step_number"),
        "title": s.get("title", ""),
        "knowledge_point": s.get("knowledge_point", ""),
        "standard_writing": s.get("standard_writing", ""),
    } for s in tg]
    cfg = TEACHER_CONFIG.get(teacher or "liangliang", TEACHER_CONFIG["liangliang"])
    try:
        c, _ = call_deepseek(TF, json.dumps(inp, ensure_ascii=False, indent=2),
                             temperature=0.3,
                             model=cfg.get("verifier", {}).get("model", "deepseek-v4-flash"),
                             reasoning_effort=cfg.get("verifier", {}).get("reasoning_effort"))
        rl = json.loads(_ej(c))
    except Exception as e:
        print(f"[Warn] _fs AI call or parse failed: {e}")
        rl = None
    ns = []
    idx = 0
    for s in steps:
        ss = dict(s)
        if ss["title"] == "\u6700\u7ec8\u7b54\u6848":
            ss["step_prompt"] = "\u8bf7\u5199\u51fa\u8fd9\u9053\u9898\u7684\u6700\u7ec8\u7b54\u6848"
            ss["step_answer"] = ss["standard_writing"]
        else:
            if rl and idx < len(rl):
                m = rl[idx]
                ss["step_prompt"] = m.get("step_prompt", ss.get("step_prompt", ""))
                ss["step_answer"] = m.get("step_answer", ss.get("step_answer", ""))
            # Fallback: use title as prompt
            if not ss.get("step_prompt"):
                label = f"\u7b2c {ss.get('step_number', '')} \u6b65" if ss.get("step_number") else "\u8fd9\u4e00\u6b65"
                ss["step_prompt"] = f"\u8bf7\u5b8c\u6210{label}\uff1a{ss.get('title', '')}\u3002\u5199\u51fa\u8fd9\u4e00\u6b65\u7684\u5177\u4f53\u8fc7\u7a0b\u548c\u6838\u5fc3\u7ed3\u679c\u3002"
            if not ss.get("step_answer"):
                ss["step_answer"] = ss.get("standard_writing", "")
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
                         model=cfg.get("verifier", {}).get("model", "deepseek-v4-flash"),
                         reasoning_effort=cfg.get("verifier", {}).get("reasoning_effort"))
    try:
        return json.loads(_ej(c))
    except Exception:
        return {"is_correct": False, "is_partial": False,
                "feedback": "抱歉，无法判断", "error_type": "其他", "error_detail": ""}

# ====== 对话式教学会话管理 ======

import uuid as _uuid
from typing import Optional, List, Dict, Any

# 读取新对话式 prompt

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
        final_answers = []
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
                    "step_prompt": s.get("step_prompt", ""),
                })
            if fa:
                final_answers.append({
                    "chunk_id": cr_.get("chunk_id", 1),
                    "chunk_type": ct,
                    "category": cn,
                    "step_number": 999,
                    "title": "最终答案",
                    "standard_writing": fa,
                    "detailed_writing": "",
                    "knowledge_point": "",
                    "step_answer": fa,
                    "step_prompt": "请写出这道题的最终答案",
                })
        # 最终答案统一放在所有步骤最后
        # steps.extend(final_answers)
        # 先入库基本数据（无论是否有 prompts）
        save_aj = dict(r) if r else {}
        save_aj["chunk_results"] = cr
        if not save_aj.get("overall_difficulty") and 'aj' in dir():
            save_aj["overall_difficulty"] = aj.get("overall_difficulty")
        if not save_aj.get("knowledge_points") and 'aj' in dir():
            save_aj["knowledge_points"] = aj.get("knowledge_points", [])
        if not save_aj.get("final_answer") and 'aj' in dir():
            save_aj["final_answer"] = aj.get("final_answer", "")
        try:
            saved_qid_first = db_save_question(question, save_aj)
        except Exception as e:
            saved_qid_first = None
            print(f"[Warn] first save_question failed: {e}")

        # 预生成每步的引导语和期望回答（仅当缺失时）
        has_all_prompts = all(s.get("step_prompt") for s in steps if s.get("title") != "最终答案")
        if not has_all_prompts:
            try:
                steps = _fs(steps, teacher)
                # 合并回 chunk_results
                si = 0
                for cr_ in cr:
                    for s in cr_.get("steps", []):
                        if si < len(steps):
                            s["step_prompt"] = steps[si].get("step_prompt", "")
                            s["step_answer"] = steps[si].get("step_answer", "")
                            si += 1
                # 更新入库（带 prompts）
                save_aj["chunk_results"] = cr
                saved_qid = db_save_question(question, save_aj)
            except Exception as e:
                saved_qid = None
                print(f"[Warn] _fs or second save_question failed: {e}")
        session_id = str(_uuid.uuid4())
        self._sessions[session_id] = {
            "session_id": session_id,
            "question_id": (saved_qid if 'saved_qid' in dir() and saved_qid is not None else saved_qid_first if 'saved_qid_first' in dir() else None),
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




def _do_chat_turn(session_id: str, student_message: str = None) -> dict:
    """执行一轮对话：使用预生成的 step_prompt/step_answer 做比对（更轻量）"""
    sess = _session_manager.get(session_id)
    if not sess:
        return {"error": "session_not_found", "detail": "会话不存在"}

    if sess["current_step"] >= sess["total_steps"]:
        return {"action": "complete", "message": "所有步骤已完成！", "session_id": session_id}

    step = sess["steps"][sess["current_step"]]

    # 情况 B：学生发了消息 → 先处理, 再决定是否展示引导（必须放在 step_introduced 之前）
    if student_message:
        _session_manager.add_message(session_id, "student", student_message)
        sess["attempt_count"] += 1

        # 检查跳过命令（不调用 AI）
        if any(kw in student_message for kw in ["跳过", "skip", "跳過", "下一步", "下一题"]):
            skipped_index = sess["current_step"]
            sess["step_results"].append({
                "step_index": skipped_index,
                "correct": True,
                "attempts": sess["attempt_count"],
                "viewed_answer": False,
            })
            sess["stats"]["skipped"] = sess["stats"].get("skipped", 0) + 1
            _session_manager.add_message(session_id, "system", f"已跳过步骤 {skipped_index+1}")
            _session_manager.advance_step(session_id)
            if sess["current_step"] < sess["total_steps"]:
                next_step = sess["steps"][sess["current_step"]]
                next_msg = next_step.get("step_prompt") or f"请完成第 {sess['current_step']+1} 步：{next_step.get('title', '')}。请写出这一步的具体过程和核心结果。"
                return {
                    "action": "advance",
                    "message": f"已跳过步骤 {skipped_index+1}。",
                    "next_step_message": next_msg,
                    "current_step": sess["current_step"] + 1,
                    "total_steps": sess["total_steps"],
                    "session_id": session_id,
                }
            else:
                return {
                    "action": "complete",
                    "message": "🎉 所有步骤已完成！",
                    "session_id": session_id,
                    "question_id": sess.get("question_id"),
                    "stats": sess["stats"],
                    "step_results": sess["step_results"],
                }

        # 处理"不会"、"提示"、"答案"等请求（不调 AI）
        if any(kw in student_message for kw in ["提示", "hint", "不会", "不懂", "不知道", "看不懂"]):
            step_answer = step.get("step_answer") or step.get("standard_writing", "")
            hint_len = min(60 + sess["attempt_count"] * 40, len(step_answer))
            partial = step_answer[:hint_len]
            if partial:
                partial = partial[:partial.rfind(" ")] if " " in partial else partial
            if len(step.get("step_answer", "")) > hint_len:
                partial += "..."
            feedback = f"给你一点提示：{partial}\n\n再想想看？"
            _session_manager.add_message(session_id, "teacher", feedback, metadata={"action": "guide"})
            return {"action": "guide", "message": feedback, "current_step": sess["current_step"] + 1, "total_steps": sess["total_steps"], "session_id": session_id}
        
        if any(kw in student_message for kw in ["答案", "answer", "看一下答案"]):
            answer = step.get("step_answer", step.get("standard_writing", ""))
            feedback = f"这一步的关键答案是：{answer}\n\n理解了之后，请继续完成下一步。"
            _session_manager.add_message(session_id, "teacher", feedback, metadata={"action": "show_answer"})
            return {"action": "guide", "message": feedback, "current_step": sess["current_step"] + 1, "total_steps": sess["total_steps"], "session_id": session_id}

    # 情况 A：当前步骤尚未展示引导 → 用 title 做引导（此刻 step_introduced 在 student_message 之后）
    if not sess["step_introduced"]:
        sess["step_introduced"] = True
        msg = step.get("step_prompt") or f"请完成第 {sess['current_step']+1} 步：{step.get('title', '')}。请写出这一步的具体过程和核心结果。"
        _session_manager.add_message(session_id, "teacher", msg, metadata={"action": "guide"})
        return {
            "action": "guide",
            "message": msg,
            "current_step": sess["current_step"] + 1,
            "total_steps": sess["total_steps"],
            "session_id": session_id,
        }

    # 情况 C：有学生消息且未被跳过/提示/答案拦截 → 用 teach_check 做比对
    if student_message:
        up = f"原题：{sess['question']}\n当前步骤引导问题：{step.get('step_prompt', '')}\n参考答案：{step.get('step_answer', step.get('standard_writing', ''))}\n学生回答：{student_message}"
        cfg = TEACHER_CONFIG.get(sess["teacher"], TEACHER_CONFIG["liangliang"])

        try:
            c, _ = call_deepseek(TC, up, temperature=0.2,
                                 model=cfg.get("verifier", {}).get("model", "deepseek-v4-flash"))
            check_result = json.loads(_ej(c))
        except Exception:
            check_result = {"is_correct": False, "is_partial": False,
                            "feedback": "抱歉，无法判断，请稍后再试。",
                            "error_type": "其他", "error_detail": ""}

        is_correct = check_result.get("is_correct", False)
        is_partial = check_result.get("is_partial", False)
        feedback = check_result.get("feedback", "")
        error_type = check_result.get("error_type")
        error_detail = check_result.get("error_detail")

        if is_correct:
            # 答对 → 记录并推进到下一步
            sess["step_results"].append({
                "step_index": sess["current_step"],
                "correct": True,
                "attempts": sess["attempt_count"],
                "viewed_answer": False,
            })
            sess["stats"]["correct"] += 1
            _session_manager.add_message(session_id, "teacher", feedback, metadata={
                "action": "advance", "is_correct": True,
                "error_type": error_type, "error_detail": error_detail})
            _session_manager.advance_step(session_id)

            if sess["current_step"] < sess["total_steps"]:
                next_step = sess["steps"][sess["current_step"]]
                next_msg = next_step.get("step_prompt") or f"好的，让我们进入下一步——{next_step.get('title', '步骤 ' + str(sess['current_step'] + 1))}。请写出这一步的具体过程和核心结果。"
                return {
                    "action": "advance",
                    "message": feedback,
                    "next_step_message": next_msg,
                    "current_step": sess["current_step"] + 1,
                    "total_steps": sess["total_steps"],
                    "session_id": session_id,
                }
            else:
                return {
                    "action": "complete",
                    "message": feedback + "\n\n🎉 你完成了所有步骤！",
                    "session_id": session_id,
                                        "question_id": sess.get("question_id"),
                    "stats": sess["stats"],
                    "step_results": sess["step_results"],
                }
        else:
            # 答错 → 留在当前步骤，返回反馈
            _session_manager.add_message(session_id, "teacher", feedback, metadata={
                "action": "guide", "is_correct": is_correct, "is_partial": is_partial,
                "error_type": error_type, "error_detail": error_detail})
            return {
                "action": "guide",
                "message": feedback,
                "is_correct": is_correct,
                "is_partial": is_partial,
                "error_type": error_type,
                "error_detail": error_detail,
                "current_step": sess["current_step"] + 1,
                "total_steps": sess["total_steps"],
                "session_id": session_id,
            }

    # 备选（不应走到这里）
    msg = step.get("step_prompt") or f"请尝试完成第 {sess['current_step']+1} 步。"
    return {"action": "guide", "message": msg, "session_id": session_id}


def teach_ack_prompt(session_id: str) -> dict:
    """前端展示完下一步引导后确认，避免提示词被跳过或重复"""
    sess = _session_manager.get(session_id)
    if not sess:
        return {"error": "session_not_found", "detail": "会话不存在"}
    if sess["current_step"] < sess["total_steps"]:
        sess["step_introduced"] = True
    return {
        "ok": True,
        "current_step": sess["current_step"] + 1,
        "total_steps": sess["total_steps"],
        "step_introduced": sess["step_introduced"],
    }


def teach_session_start(question: str, teacher: str = None) -> dict:
    """对外：创建教学会话，返回会话信息和第一轮 AI 引导"""
    result = _session_manager.create(question, teacher)
    if result.get("error"):
        return result

    result["steps"] = result.get("steps", [])
    result["chunk_results"] = result.get("chunk_results", [])

    # 使用预生成的步骤引导作为第一轮消息（零 AI 调用）
    sess = _session_manager.get(result["session_id"])
    first_step = sess["steps"][0] if sess["steps"] else {}
    first_msg = first_step.get("step_prompt") or f"请尝试完成第 1 步：{first_step.get('title', '')}"
    sess["step_introduced"] = True
    _session_manager.add_message(result["session_id"], "teacher", first_msg, metadata={"action": "guide"})

    return {
        "session_id": result["session_id"],
        "question_id": sess.get("question_id"),
        "action": "guide",
        "message": first_msg,
        "steps": sess["steps"],
        "chunk_results": sess["chunk_results"],
        "total_steps": sess["total_steps"],
        "current_step": 1,
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
        "question_id": sess.get("question_id"),
        "question": sess["question"],
        "teacher": sess["teacher"],
        "steps": sess["steps"],
        "chunk_results": sess.get("chunk_results", []),
        "current_step": sess["current_step"],
        "total_steps": sess["total_steps"],
        "messages": sess["messages"],
        "stats": sess["stats"],
        "step_results": sess["step_results"],
        "step_introduced": sess.get("step_introduced", False),
        "overall_difficulty": sess.get("overall_difficulty"),
    }
