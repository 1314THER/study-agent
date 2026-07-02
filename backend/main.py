from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import solve
from backend.database import init_db, get_all_questions
from backend.categories import get_all_categories

app = FastAPI(title="AI学习伴侣")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class SolveRequest(BaseModel):
    question: str

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def home():
    return {"message": "AI学习伴侣后端已启动"}

@app.post("/solve")
def solve_question(req: SolveRequest):
    """搜题 → 调做题系统 → 返回结构化答案（含 category / difficulty / steps）"""
    return solve(req.question)

@app.get("/questions")
def list_questions():
    """查看历史题目（含独立字段：category_level1, category_level2, difficulty_level, difficulty_score 等）"""
    return get_all_questions()

@app.get("/categories")
def categories():
    """获取知识点分类列表"""
    return get_all_categories()
