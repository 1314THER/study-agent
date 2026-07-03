from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, List
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import solve, solve_multi, step_solver_only, step_verify_all, step_final_check, _xuebile, _extract_solver_status
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

class Step1Request(BaseModel):
    question: str
    question_type: Optional[str] = Field(None, description="题型（可选）")

class Step2Request(BaseModel):
    question: str = Field(..., description="原题")
    content: str = Field(..., description="Solver 输出的完整解答")
    category: Optional[str] = Field(None, description="板块")


class Step3Request(BaseModel):
    question: str = Field(..., description="原题")
    chunk_results: str = Field(..., description="Verifier 输出的各块结果 JSON")
    solver_difficulty: Optional[int] = Field(None, description="雪峰难度系数")

@app.post("/solve/step1")
def api_step1(req: Step1Request):
    """第1步：解答"""
    result = step_solver_only(req.question, req.question_type)
    status = _extract_solver_status(result["content"])
    if status:
        return _xuebile(status, f"Solver 判定：{status}")
    return result

@app.post("/solve/step2")
@app.post("/solve/step2")
def api_step2(req: Step2Request):
    result = step_verify_all(req.content, req.question, req.category)
    return result


@app.post("/solve/step3")
def api_step3(req: Step3Request):
    import json
    chunk_results = json.loads(req.chunk_results)
    token_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    final = step_final_check(req.question, chunk_results, [], token_total, req.solver_difficulty)
    return final


@app.post("/solve")
def api_solve(req: SolveRequest):
    """完整多块求解"""
    return solve_multi(req.question, req.question_type)

@app.get("/")
def home():
    return {"message": "你好，我是张雪峰老师 - 后端已启动"}

@app.get("/questions")
def list_questions():
    return get_all_questions()

@app.get("/categories")
def categories():
    return get_all_categories()
