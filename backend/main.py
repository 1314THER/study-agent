from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from pydantic import BaseModel, Field
from typing import Optional, List
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import step_solver_only, step_verify_all, step_final_check, _xuebile, _extract_solver_status
from backend.database import init_db, get_all_questions, search_questions, delete_question
from backend.categories import get_all_categories

app = FastAPI(title="你好，我是张雪峰老师")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    init_db()

class SolveRequest(BaseModel):
    question: str
    question_type: Optional[str] = Field(None, description="题型（可选）")
    teacher: Optional[str] = Field(None, description="老师（可选）")
    save: bool = True

class Step1Request(BaseModel):
    question: str
    question_type: Optional[str] = Field(None, description="题型（可选）")
    teacher: Optional[str] = Field(None, description="老师（可选）")

class Step2Request(BaseModel):
    question: str = Field(..., description="原题")
    content: str = Field(..., description="Solver 输出的完整解答")
    category: Optional[str] = Field(None, description="板块")
    question_type: Optional[str] = Field(None, description="题型")
    teacher: Optional[str] = Field(None, description="老师（可选）")


class Step3Request(BaseModel):
    question: str = Field(..., description="原题")
    chunk_results: str = Field(..., description="Verifier 输出的各块结果 JSON")
    teacher: Optional[str] = Field(None, description="老师（可选）")
    save: bool = False

# ---------- 错因标定 ----------
_VALID_MISTAKE_TYPES = {"符号错误", "计算错误", "公式记错",
                        "知识性错误", "审题错误", "思路错误", "其他"}

class StepErrorRequest(BaseModel):
    step_number: int = Field(..., ge=1, description="步骤编号")
    chunk_id: int = Field(..., ge=1, description="块编号")
    mistake_type: str = Field(..., description="错因类型")
    mistake_detail: str = Field("", description="错因详细说明")

@app.post("/solve/step1")
def api_step1(req: Step1Request):
    """第1步：解答"""
    result = step_solver_only(req.question, req.question_type, teacher=req.teacher)
    if result.get("error"):
        return result
    return result

@app.post("/solve/step2")
def api_step2(req: Step2Request):
    result = step_verify_all(req.content, req.question, req.category, question_type=req.question_type, teacher=req.teacher)
    return result
class SaveQuestionRequest(BaseModel):
    question: str
    answer_json: dict


@app.post("/questions/save")
def api_save_question(req: SaveQuestionRequest):
    """保存题目到个人题库（如已存在则提示）"""
    from backend.database import find_question, save_question
    existing = find_question(req.question)
    if existing:
        return {"saved": False, "reason": "already_exists", "message": "该题已在个人题库中"}
    # 从 chunk_results 提取分类和难度（兼容前端未传的情况）
    chunk_results = req.answer_json.get("chunk_results", [])
    first = chunk_results[0] if chunk_results else {}
    req.answer_json["category"] = first.get("category")
    req.answer_json["difficulty"] = req.answer_json.get("overall_difficulty") or first.get("difficulty")
    req.answer_json["question_type"] = first.get("chunk_type")
    # 将答案结构化数据写入数据库，返回题目 ID
    from backend.database import save_question as _save_q
    qid = _save_q(req.question, req.answer_json)
    return {"saved": True, "id": qid, "message": "已加入个人题库"}




@app.post("/solve/step3")
def api_step3(req: Step3Request):
    import json
    chunk_results = json.loads(req.chunk_results)
    token_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    final = step_final_check(req.question, chunk_results, [], token_total, teacher=req.teacher)

    if req.save:
        from backend.database import save_question
        first = chunk_results[0] if chunk_results else {}
        final["category"] = first.get("category")
        final["difficulty"] = final.get("overall_difficulty") or first.get("difficulty")
        final["question_type"] = first.get("chunk_type")
        try:
            from backend.database import save_question as _save_q3
            saved_qid = _save_q3(req.question, final)
            final["saved_question_id"] = saved_qid
        except Exception as e:
            print(f"[Warn] 保存到数据库失败: {e}")

    return final


@app.get("/")
def home():
    return HTMLResponse("""<html><head><script>location.href="/index.html"</script></head><body><a href="/index.html">进入数学最强大脑</a></body></html>""")

@app.get("/questions")
def list_questions():
    return get_all_questions()


@app.get("/questions/search")
def api_search_questions(
    q: str = "",
    category: str = "",
    difficulty: str = "",
    question_type: str = "",
    limit: int = 200,
    mode: str = "content",
    error_type: str = "",
    page: int = 1,
    page_size: int = 0,
):
    """搜索个人题库：关键词（空格分隔为 AND 匹配）+ 板块 + 难度 + 题型筛选
    mode="content": 仅搜索题目原文（默认）
    mode="global":  同时搜索板块、知识点、错因
    error_type: 错因筛选（none=无错因，具体类型=按类型筛选，空=全部）"""
    if mode not in ("content", "global"):
        mode = "content"
    keywords = [kw.strip() for kw in q.split() if kw.strip()] if q else None
    categories = [c.strip() for c in category.split(",") if c.strip()] if category else None
    difficulties = [d.strip() for d in difficulty.split(",") if d.strip()] if difficulty else None
    types = [t.strip() for t in question_type.split(",") if t.strip()] if question_type else None
    et = error_type if error_type else None
    ps = page_size if page_size > 0 else None
    return search_questions(keywords, categories, difficulties, types, limit=limit, mode=mode, error_type=et, page=page, page_size=ps)


@app.get("/questions/errors")
def api_questions_with_errors():
    """列出所有有错因标记的题目（摘要信息）"""
    from backend.database import get_questions_with_errors
    return get_questions_with_errors()


@app.post("/questions/{qid}/exam-touch")
def api_exam_touch(qid: int):
    """标记题目最近一次组卷时间"""
    from backend.database import update_question_time
    try:
        update_question_time(qid, "last_exam_at")
        return {"touched": True, "id": qid}
    except Exception as e:
        return {"touched": False, "error": str(e)}


@app.get("/questions/{qid}")
def get_question(qid: int):
    """返回单题完整记录（含 answer_json + step_errors），同时记录查看时间"""
    from backend.database import update_question_time
    try:
        update_question_time(qid, "last_viewed_at")
    except Exception:
        pass
    from backend.database import get_question_by_id, get_step_errors
    result = get_question_by_id(qid)
    if result is None:
        return {"error": "not_found", "id": qid}
    result["step_errors"] = get_step_errors(qid)
    return result


@app.post("/questions/{qid}/step-error")
def api_add_step_error(qid: int, req: StepErrorRequest):
    """记录某题某步的错因"""
    from backend.database import update_question_time
    update_question_time(qid, "last_edited_at")
    if req.mistake_type not in _VALID_MISTAKE_TYPES:
        return {"error": "invalid_mistake_type",
                "valid_types": list(_VALID_MISTAKE_TYPES)}
    from backend.database import add_step_error
    try:
        error_id = add_step_error(
            question_id=qid,
            step_number=req.step_number,
            chunk_id=req.chunk_id,
            mistake_type=req.mistake_type,
            mistake_detail=req.mistake_detail
        )
        return {"id": error_id, "saved": True}
    except Exception as e:
        return {"error": str(e), "saved": False}


@app.delete("/questions/{qid}/step-error/{eid}")
def api_delete_step_error(qid: int, eid: int):
    """删除一条错因记录"""
    from backend.database import delete_step_error, update_question_time
    update_question_time(qid, "last_edited_at")
    ok = delete_step_error(eid, qid)
    if not ok:
        return {"deleted": False, "message": "未找到该错因记录"}
    return {"deleted": True, "id": eid}


@app.get("/categories")
def categories():
    return get_all_categories()


@app.delete("/questions/{qid}")
def api_delete_question(qid: int):
    """删除个人题库中的一道题"""
    ok = delete_question(qid)
    if not ok:
        return {"deleted": False, "message": "未找到该题"}
    return {"deleted": True, "id": qid, "message": "已删除"}




class AiSearchRequest(BaseModel):
    query: str
    limit: int = 20


@app.post("/questions/ai-search")
def api_ai_search_questions(req: AiSearchRequest):
    """AI 语义搜索（预留）"""
    from backend.database import ai_search_questions
    return ai_search_questions(req.query, req.limit)


class AiAssembleRequest(BaseModel):
    query: str


@app.post("/exam/ai-assemble")
def api_ai_assemble(req: AiAssembleRequest):
    """AI 一键组卷（预留）"""
    return {"query": req.query, "results": [], "total": 0, "note": "AI 组卷功能开发中"}


# ---- Static files: serve frontend (must be last) ----
import os
_frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_frontend_path):
    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")
