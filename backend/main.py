from fastapi import FastAPI, UploadFile, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from pydantic import BaseModel, Field
from typing import Optional, List
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import step_solver_only, step_verify_all, step_final_check, _xuebile, _extract_solver_status
from backend.teach import teach_start, teach_check, teach_find_or_format, teach_session_start, teach_session_chat, teach_get_session
from backend.multimodal import parse_file, get_supported_extensions
from backend.database import (
    init_db, get_all_questions, search_questions, delete_question,
    get_question_lists, create_question_list, delete_question_list,
    rename_question_list, add_question_to_lists, remove_question_from_list,
    get_list_questions, get_wrong_questions, update_question_source,
)
from backend.categories import get_all_categories
from backend.steps import get_step_structure, get_all_question_types

app = FastAPI(title="你好，我是张雪峰老师")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_cache_html(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    from fastapi.responses import JSONResponse
    from starlette import status
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "server_error", "detail": str(exc)[:200]},
    )

@app.on_event("startup")
def startup():
    init_db()
    from backend.patterns import init_mastery_db, sync_mother_questions
    init_mastery_db()
    sync_mother_questions()


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
    content: Optional[str] = Field(None, description="Solver 原始解答，Formatter 失败时用于重跑 Verifier")
    category: Optional[str] = Field(None, description="板块（可选）")
    question_type: Optional[str] = Field(None, description="题型（可选）")

# ---------- 错因标定 ----------
_VALID_MISTAKE_TYPES = {"符号错误", "计算错误", "公式记错",
                        "知识性错误", "审题错误", "思路错误", "其他"}

class StepErrorRequest(BaseModel):
    step_number: int = Field(..., ge=1, description="步骤编号")
    chunk_id: int = Field(..., ge=1, description="块编号")
    mistake_type: str = Field(..., description="错因类型")
    mistake_detail: str = Field("", description="错因详细说明")
    student_input: Optional[str] = Field(None, description="学生当时的错误作答")

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
    source_type: Optional[str] = Field(None, description="来源类型：ai生成/高考题/模拟题/精选母题")
    source_meta: Optional[dict] = Field(None, description="来源二级标签，如卷子名/题号/参考题ID/母题ID")


@app.post("/questions/save")
def api_save_question(req: SaveQuestionRequest):
    """保存题目到个人题库（已存在时也返回 ID）"""
    from backend.database import save_question as _save_q
    # 无论是否存在都写入（INSERT OR REPLACE 处理重复）
    chunk_results = req.answer_json.get("chunk_results", [])
    first = chunk_results[0] if chunk_results else {}
    req.answer_json["category"] = first.get("category")
    req.answer_json["difficulty"] = req.answer_json.get("overall_difficulty") or first.get("difficulty")
    req.answer_json["question_type"] = first.get("chunk_type")
    if req.source_type:
        req.answer_json["source_type"] = req.source_type
    if req.source_meta is not None:
        req.answer_json["source_meta"] = req.source_meta
    qid = _save_q(req.question, req.answer_json)
    if qid:
        return {"saved": True, "id": qid, "message": "已加入个人题库"}
    return {"saved": False, "message": "保存失败"}




@app.post("/solve/step3")
def api_step3(req: Step3Request):
    import json
    chunk_results = json.loads(req.chunk_results)
    token_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    final = step_final_check(
        req.question,
        chunk_results,
        [],
        token_total,
        teacher=req.teacher,
        solver_content=req.content,
        verifier_category=req.category,
        question_type=req.question_type,
    )

    if req.save:
        from backend.database import save_question
        first = chunk_results[0] if chunk_results else {}
        final["category"] = first.get("category")
        final["difficulty"] = final.get("overall_difficulty") or first.get("difficulty")
        final["question_type"] = first.get("chunk_type")
        try:
            from backend.database import save_question as _save_q3
            save_aj = dict(final)
            save_aj.pop("error", None)
            save_aj.pop("formatter_note", None)
            saved_qid = _save_q3(req.question, save_aj)
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
    source_type: str = "",
):
    """搜索个人题库：关键词（空格分隔为 AND 匹配）+ 板块 + 难度 + 题型 + 来源筛选
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
    st = source_type if source_type else None
    return search_questions(keywords, categories, difficulties, types, limit=limit, mode=mode, error_type=et, page=page, page_size=ps, source_type=st)


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
            mistake_detail=req.mistake_detail,
            student_input=req.student_input or "",
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
    try:
        from backend.patterns import delete_question_links
        delete_question_links(qid)
    except Exception as e:
        print(f"[Warn] 清理母题库关联失败: {e}")
    return {"deleted": True, "id": qid, "message": "已删除"}


class AddMotherQuestionRequest(BaseModel):
    question_id: int
    category: str
    name: str
    key: Optional[str] = Field(None, description="套路稳定编号")
    description: Optional[str] = Field("", description="套路说明")


@app.get("/patterns")
def api_patterns():
    """返回母题套路列表"""
    from backend.patterns import get_patterns
    return get_patterns()


@app.post("/patterns/mother")
def api_add_mother_question(req: AddMotherQuestionRequest):
    """将一道题登记为母题并写入 patterns.yaml / mastery.db"""
    from backend.patterns import add_mother_question
    try:
        return add_mother_question(
            question_id=req.question_id,
            category=req.category,
            name=req.name,
            key=req.key,
            description=req.description,
        )
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "invalid_mother", "detail": str(e)})


class UpdatePatternRequest(BaseModel):
    category: Optional[str] = Field(None, description="板块")
    name: Optional[str] = Field(None, description="套路名")
    description: Optional[str] = Field(None, description="套路说明")
    key: Optional[str] = Field(None, description="套路稳定编号")
    max_time_seconds: Optional[int] = Field(None, description="单题限时（秒）")


class PatternQuestionRequest(BaseModel):
    question_id: int
    role: str = Field(..., description="mother/variant1/variant2/variant3")


@app.put("/patterns/{pattern_id}")
def api_update_pattern(pattern_id: int, req: UpdatePatternRequest):
    from backend.patterns import update_pattern
    try:
        return update_pattern(
            pattern_id=pattern_id,
            category=req.category,
            name=req.name,
            description=req.description,
            key=req.key,
            max_time_seconds=req.max_time_seconds,
        )
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "invalid_pattern", "detail": str(e)})


@app.delete("/patterns/{pattern_id}")
def api_delete_pattern(pattern_id: int):
    from backend.patterns import delete_pattern
    ok = delete_pattern(pattern_id)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": "套路不存在"})
    return {"deleted": True, "id": pattern_id}


@app.post("/patterns/{pattern_id}/questions")
def api_link_pattern_question(pattern_id: int, req: PatternQuestionRequest):
    from backend.patterns import link_question_to_pattern
    try:
        return link_question_to_pattern(pattern_id, req.question_id, req.role)
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "invalid_link", "detail": str(e)})


@app.delete("/patterns/{pattern_id}/questions/{question_id}")
def api_unlink_pattern_question(pattern_id: int, question_id: int,
                                role: Optional[str] = Query(None, description="可选：只移除指定角色")):
    from backend.patterns import unlink_question_from_pattern
    ok = unlink_question_from_pattern(pattern_id, question_id, role)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": "未找到关联"})
    return {"unlinked": True}


@app.post("/patterns/export-yaml")
def api_export_patterns_yaml():
    """把当前 mastery.db 中的母题套路定型导出到 patterns.yaml"""
    from backend.patterns import export_patterns_yaml
    data = export_patterns_yaml()
    return {"exported": True, "patterns": data}


@app.post("/patterns/sync")
def api_sync_patterns():
    """把题库里的精选母题同步为母题看板套路"""
    from backend.patterns import sync_mother_questions
    return sync_mother_questions()


@app.get("/patterns/{pattern_id}/loop")
def api_get_pattern_loop(pattern_id: int):
    """返回套路循环页数据：母题/变式/限时/掌握状态"""
    from backend.patterns import get_pattern_loop
    try:
        return get_pattern_loop(pattern_id)
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(e)})


@app.get("/patterns/calendar")
def api_pattern_calendar():
    """套路巩固日历（UTC+8）"""
    from backend.patterns import get_pattern_calendar
    return get_pattern_calendar()


@app.get("/patterns/calendar.ics")
def api_pattern_calendar_ics():
    """导出套路巩固安排为 .ics 日历文件"""
    from fastapi.responses import Response
    from backend.patterns import get_pattern_calendar_ics
    content = get_pattern_calendar_ics()
    return Response(
        content=content,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="math-review-calendar.ics"'},
    )


class PatternAttemptRequest(BaseModel):
    question_id: int
    role: str = Field(..., description="mother/variant1/variant2/variant3")
    correct: bool
    is_first_try: bool = False
    duration_seconds: int = 0


@app.post("/patterns/{pattern_id}/attempt")
def api_record_pattern_attempt(pattern_id: int, req: PatternAttemptRequest):
    from backend.patterns import record_attempt
    aid = record_attempt(
        pattern_id=pattern_id,
        question_id=req.question_id,
        role=req.role,
        correct=req.correct,
        is_first_try=req.is_first_try,
        duration_seconds=req.duration_seconds,
    )
    return {"attempt_id": aid, "saved": True}


class EnsureVariantsRequest(BaseModel):
    teacher: Optional[str] = Field("liangliang", description="老师")


class PatternCompleteRequest(BaseModel):
    passed: bool


class PatternCheckRequest(BaseModel):
    question_id: int
    user_answer: str
    teacher: Optional[str] = Field("liangliang", description="老师")


@app.post("/patterns/{pattern_id}/complete")
def api_complete_pattern_loop(pattern_id: int, req: PatternCompleteRequest):
    """完成一次套路循环，推进掌握状态"""
    from backend.patterns import complete_pattern_loop
    return complete_pattern_loop(pattern_id, req.passed)


@app.post("/patterns/{pattern_id}/check")
def api_check_pattern_answer(pattern_id: int, req: PatternCheckRequest):
    """套路循环中由 AI 比对学生输入的答案"""
    from backend.patterns import check_pattern_answer
    try:
        return check_pattern_answer(
            pattern_id, req.question_id, req.user_answer, teacher=req.teacher
        )
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(e)})


@app.post("/patterns/{pattern_id}/ensure-variants")
def api_ensure_pattern_variants(pattern_id: int, req: EnsureVariantsRequest):
    """变式1/2/3 为空时 AI 生成并持久化"""
    from backend.patterns import ensure_variants
    try:
        return ensure_variants(pattern_id, teacher=req.teacher or "liangliang")
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "generate_failed", "detail": str(e)[:200]})


@app.get("/boards")
def api_get_boards():
    """返回全部板块闯关地图"""
    from backend.patterns import get_boards
    return get_boards()


class BoardNodePayload(BaseModel):
    question_id: int
    x: float = 0
    y: float = 0


class BoardEdgePayload(BaseModel):
    from_question_id: int
    to_question_id: int


class BoardLayoutRequest(BaseModel):
    nodes: List[BoardNodePayload] = []
    edges: List[BoardEdgePayload] = []


@app.put("/boards/{board_id}")
def api_save_board_layout(board_id: int, req: BoardLayoutRequest):
    """整体保存某板块地图的节点与连线"""
    from backend.patterns import save_board_layout
    try:
        return save_board_layout(
            board_id,
            [{"question_id": n.question_id, "x": n.x, "y": n.y} for n in req.nodes],
            [{"from_question_id": e.from_question_id, "to_question_id": e.to_question_id} for e in req.edges],
        )
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "invalid_board", "detail": str(e)})


class AiSearchRequest(BaseModel):
    query: str
    limit: int = 20


class GenerateVariantsRequest(BaseModel):
    count: int = Field(3, ge=1, le=5, description="生成数量")
    teacher: Optional[str] = Field("liangliang", description="生成与校验老师")


@app.post("/questions/{qid}/generate")
def api_generate_variants(qid: int, req: GenerateVariantsRequest):
    """基于一道已有题目及其学生错因，AI 仿造变式题并自动入库"""
    from backend.generate import generate_variants
    try:
        return generate_variants(qid, count=req.count, teacher=req.teacher or "liangliang")
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(e)})


@app.post("/questions/{qid}/generate/async")
def api_generate_variants_async(qid: int, req: GenerateVariantsRequest):
    """异步启动 AI 仿题任务，返回 job_id 供前端轮询进度"""
    from backend.generate import start_generate_job
    try:
        return start_generate_job(qid, count=req.count, teacher=req.teacher or "liangliang")
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(e)})


@app.get("/generate-jobs/{job_id}")
def api_get_generate_job(job_id: str):
    """获取 AI 仿题任务的进度与结果"""
    from backend.generate import get_generate_job
    job = get_generate_job(job_id)
    if not job:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": "任务不存在"})
    return job


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


@app.post("/multimodal/parse")
async def api_multimodal_parse(file: UploadFile):
    """上传文件，解析为 LaTeX 题目列表"""
    import tempfile, os, shutil
    
    ext = os.path.splitext(file.filename or "upload")[1].lower()
    if ext not in get_supported_extensions():
        return {"error": f"不支持的文件格式: {ext}", "supported": get_supported_extensions()}
    
    # 保存到临时文件
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename or f"upload{ext}")
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        questions = parse_file(tmp_path, file.filename or "")
        return {"questions": questions, "total": len(questions)}
    except Exception as e:
        return {"error": str(e)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)



@app.get("/steps")
def api_steps():
    """返回 steps.yaml 中所有题型的两级步骤结构"""
    return {
        "types": [
            {
                "name": qtype,
                "has_predefined": bool(get_step_structure(qtype)),
                "steps": get_step_structure(qtype),
            }
            for qtype in get_all_question_types()
        ]
    }



# ---------- 教学系统 ----------
class TeachStartRequest(BaseModel):
    question: str
    teacher: Optional[str] = Field(None, description="老师（可选）")

class TeachCheckRequest(BaseModel):
    question: str
    step_prompt: str
    step_answer: str
    user_answer: str
    teacher: Optional[str] = Field(None, description="老师（可选）")


@app.post("/teach/find")
def api_teach_find(req: TeachStartRequest):
    """查找题目是否已在题库中，有教学步骤直接返回，有标准步骤转换后返回"""
    from backend.database import find_question
    result = find_question(req.question)
    if result and result.get("chunk_results"):
        chunk_results = result["chunk_results"]
        all_steps = []
        for cr in chunk_results:
            chunk_type = cr.get("chunk_type", "整体")
            category_name = cr.get("category", {}).get("level1", "")
            final_answer = cr.get("final_answer", "")
            for step in cr.get("steps", []):
                all_steps.append({
                    "chunk_id": cr.get("chunk_id", 1),
                    "chunk_type": chunk_type,
                    "category": category_name,
                    "step_number": step.get("step_number", 0),
                    "title": step.get("title", ""),
                    "step_level1": step.get("step_level1", ""),
                    "standard_writing": step.get("standard_writing", ""),
                    "detailed_writing": step.get("detailed_writing", ""),
                    "knowledge_point": step.get("knowledge_point", ""),
                })
            if final_answer:
                all_steps.append({
                    "chunk_id": cr.get("chunk_id", 1),
                    "chunk_type": chunk_type,
                    "category": category_name,
                    "step_number": 999,
                    "title": "最终答案",
                    "step_level1": "",
                    "standard_writing": final_answer,
                    "detailed_writing": "",
                    "knowledge_point": "",
                })
        first_cr = chunk_results[0] if chunk_results else {}
        return {
            "found": True,
            "question": req.question,
            "category": category_name,
            "steps": all_steps,
            "total_steps": len(all_steps),
            "chunk_results": chunk_results,
            "overall_difficulty": result.get("overall_difficulty"),
            "from_db": True,
        }
    return {"found": False}


@app.post("/teach/start")
def api_teach_start(req: TeachStartRequest):
    """开启教学会话：解题并返回所有步骤"""
    result = teach_start(req.question, teacher=req.teacher)
    return result


@app.post("/teach/check")
def api_teach_check(req: TeachCheckRequest):
    """检查学生当前步骤的作答"""
    result = teach_check(req.question, req.step_prompt, req.step_answer, req.user_answer, teacher=req.teacher)
    return result


# ---------- 对话式教学会话 ----------
class TeachSessionStartRequest(BaseModel):
    question: str
    teacher: Optional[str] = Field(None, description="老师（可选）")


class TeachSessionChatRequest(BaseModel):
    message: str


@app.post("/teach/session/start")
def api_teach_session_start(req: TeachSessionStartRequest):
    """创建新的对话式教学会话"""
    result = teach_session_start(req.question, teacher=req.teacher)
    return result


@app.post("/teach/session/{session_id}/chat")
def api_teach_session_chat(session_id: str, req: TeachSessionChatRequest):
    """在现有会话中发送学生消息"""
    if not teach_get_session(session_id):
        return {"error": "session_not_found", "detail": "会话不存在"}
    result = teach_session_chat(session_id, req.message)
    return result


@app.post("/teach/session/{session_id}/ack")
def api_teach_session_ack(session_id: str):
    """前端展示完下一步引导后确认"""
    from backend.teach import teach_ack_prompt
    return teach_ack_prompt(session_id)


@app.get("/teach/session/{session_id}")
def api_teach_get_session(session_id: str):
    """获取会话完整信息"""
    result = teach_get_session(session_id)
    if not result:
        return {"error": "session_not_found", "detail": "会话不存在"}
    return result



# ---------- 题单管理 ----------

@app.get("/question-lists")
def api_get_question_lists():
    """获取所有题单（含错题动态题单）"""
    return get_question_lists()


class CreateListRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="题单名")


@app.post("/question-lists")
def api_create_question_list(req: CreateListRequest):
    """创建新的用户题单"""
    lid = create_question_list(req.name)
    return {"id": lid, "name": req.name, "list_type": "user", "created": True}


class RenameListRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="新题单名")


@app.put("/question-lists/{list_id}")
def api_rename_question_list(list_id: int, req: RenameListRequest):
    """重命名题单（系统题单不可改名）"""
    ok = rename_question_list(list_id, req.name)
    if not ok:
        return {"error": "rename_failed", "message": "题单不存在或为系统题单"}
    return {"ok": True, "name": req.name}


@app.delete("/question-lists/{list_id}")
def api_delete_question_list(list_id: int):
    """删除用户题单（系统题单不可删除）"""
    ok = delete_question_list(list_id)
    if not ok:
        return {"error": "delete_failed", "message": "题单不存在或为系统题单"}
    return {"ok": True, "deleted_id": list_id}


@app.get("/question-lists/{target}/questions")
def api_get_list_questions(
    target: str,
    q: str = "",
    category: str = "",
    difficulty: str = "",
    question_type: str = "",
    error_type: str = "",
    source_type: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0),
):
    """获取指定题单下的题目（支持筛选和分页）
    target 可以是:
      - "all" 代表全部题单
      - "wrong" 代表错题（动态查询）
      - 数字 id 代表具体题单
    """
    keywords = [kw.strip() for kw in q.split() if kw.strip()] if q else None
    categories = [c.strip() for c in category.split(",") if c.strip()] if category else None
    difficulties = [d.strip() for d in difficulty.split(",") if d.strip()] if difficulty else None
    types = [t.strip() for t in question_type.split(",") if t.strip()] if question_type else None
    et = error_type if error_type else None
    ps = page_size if page_size > 0 else None
    st = source_type if source_type else None

    if target == "wrong":
        return get_wrong_questions(keywords, categories, difficulties, types, et, page, ps, st)
    try:
        list_id = int(target)
    except ValueError:
        return {"error": "invalid_target", "message": "target 必须是 all、wrong 或数字 ID"}
    return get_list_questions(list_id, keywords, categories, difficulties, types, et, page, ps, st)


class AddToListRequest(BaseModel):
    list_ids: List[int] = Field(..., description="要加入的题单 ID 列表")


@app.post("/questions/{qid}/lists")
def api_add_question_to_lists(qid: int, req: AddToListRequest):
    """将题目加入指定题单"""
    if not req.list_ids:
        return {"added": 0, "skipped": 0}
    result = add_question_to_lists(qid, req.list_ids)
    from backend.database import update_question_time
    try:
        update_question_time(qid, "last_edited_at")
    except Exception:
        pass
    return result


@app.delete("/questions/{qid}/lists/{list_id}")
def api_remove_question_from_list(qid: int, list_id: int):
    """从题单中移除题目（软删除）"""
    ok = remove_question_from_list(qid, list_id)
    if not ok:
        return {"error": "remove_failed", "message": "系统题单不可移除或关联不存在"}
    return {"ok": True, "removed": True}


@app.get("/questions/{qid}/lists")
def api_get_question_lists(qid: int):
    """获取题目所在的所有题单 ID"""
    from backend.database import get_question_list_ids
    return {"list_ids": get_question_list_ids(qid)}


class SourceTypeRequest(BaseModel):
    source_type: str = Field(..., description="来源类型：ai生成/高考题/模拟题/精选母题")
    source_meta: Optional[dict] = Field(None, description="来源二级标签，如卷子名/题号/参考题ID/母题ID")


@app.put("/questions/{qid}/source-type")
def api_update_source_type(qid: int, req: SourceTypeRequest):
    """更新题目的来源类型标签"""
    if req.source_type not in ("ai\u751f\u6210", "\u9ad8\u8003\u9898", "\u6a21\u62df\u9898", "\u7cbe\u9009\u6bcd\u9898"):
        return {"error": "invalid_source_type", "valid_types": ["ai\u751f\u6210", "\u9ad8\u8003\u9898", "\u6a21\u62df\u9898", "\u7cbe\u9009\u6bcd\u9898"]}
    ok = update_question_source(qid, req.source_type, req.source_meta)
    if not ok:
        return {"error": "update_failed"}
    return {"ok": True, "source_type": req.source_type, "source_meta": req.source_meta}

# ---- Static files: serve frontend (must be last) ----

import os
_frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_frontend_path):
    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")
