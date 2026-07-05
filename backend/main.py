from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, List
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import step_solver_only, step_verify_all, step_final_check, _xuebile, _extract_solver_status
from backend.database import init_db, get_all_questions
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
    """保存题目到错题本（如已存在则提示）"""
    from backend.database import find_question, save_question
    existing = find_question(req.question)
    if existing:
        return {"saved": False, "reason": "already_exists", "message": "该题已在错题本中"}
    # 从 chunk_results 提取分类和难度（兼容前端未传的情况）
    chunk_results = req.answer_json.get("chunk_results", [])
    first = chunk_results[0] if chunk_results else {}
    req.answer_json["category"] = first.get("category")
    req.answer_json["difficulty"] = first.get("difficulty")
    # 将答案结构化数据写入数据库
    save_question(req.question, req.answer_json)
    return {"saved": True, "message": "已加入错题本"}




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
        final["difficulty"] = first.get("difficulty")
        try:
            save_question(req.question, final)
        except Exception as e:
            print(f"[Warn] 保存到数据库失败: {e}")

    return final


@app.get("/")
def home():
    return {"message": "你好，我是张雪峰老师 - 后端已启动"}

@app.get("/questions")
def list_questions():
    return get_all_questions()

@app.get("/questions/{qid}")
def get_question(qid: int):
    """返回单题完整记录（含 answer_json）"""
    from backend.database import get_question_by_id
    result = get_question_by_id(qid)
    if result is None:
        return {"error": "not_found", "id": qid}
    return result

@app.get("/categories")
def categories():
    return get_all_categories()
