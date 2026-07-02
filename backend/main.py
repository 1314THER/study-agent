from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import solve, step_solver, step_verifier, step_formatter
from backend.database import init_db, get_all_questions
from backend.categories import get_all_categories

app = FastAPI(title="AI学习伴侣")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    init_db()

# ---------- 请求格式 ----------
class SolveRequest(BaseModel):
    question: str

class Step1Request(BaseModel):
    question: str

class Step2Request(BaseModel):
    content: str

class Step3Request(BaseModel):
    content: str
    original_question: str = None

# ---------- 分步接口 ----------
@app.post("/solve/step1")
def api_step1(req: Step1Request):
    """第1步：解题"""
    return step_solver(req.question)

@app.post("/solve/step2")
def api_step2(req: Step2Request):
    """第2步：校验"""
    return step_verifier(req.content)

@app.post("/solve/step3")
def api_step3(req: Step3Request):
    """第3步：格式化 + 入库"""
    return step_formatter(req.content, req.original_question)

# ---------- 原接口 ----------
@app.get("/")
def home():
    return {"message": "AI学习伴侣后端已启动"}

@app.post("/solve")
def api_solve(req: SolveRequest):
    """完整三步（旧接口，一次性返回）"""
    return solve(req.question)

@app.get("/questions")
def list_questions():
    return get_all_questions()

@app.get("/categories")
def categories():
    return get_all_categories()
