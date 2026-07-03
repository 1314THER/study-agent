from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, List
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import solve, solve_multi, step_solver_only, step_verify_format_chunk
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
    chunk_content: str = Field(..., description="块内容")
    chunk_id: int = Field(..., description="块编号")
    chunk_type: str = Field("整体", description="块类型")
    chunk_category: Optional[str] = Field(None, description="板块")
    question: str = Field(..., description="母题")
    solved_json: str = Field("[]", description="已解的块(JSON)")

@app.post("/solve/step1")
def api_step1(req: Step1Request):
    """第1步：切块+解答"""
    return step_solver_only(req.question, req.question_type)

@app.post("/solve/step2")
def api_step2(req: Step2Request):
    """第2步：校验+格式化一个块"""
    import json
    solved = json.loads(req.solved_json) if req.solved_json else []
    chunk = {"id": req.chunk_id, "type": req.chunk_type, "content": req.chunk_content, "category": req.chunk_category}
    return step_verify_format_chunk(chunk, req.question, solved)

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
