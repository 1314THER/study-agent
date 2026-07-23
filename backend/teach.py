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
