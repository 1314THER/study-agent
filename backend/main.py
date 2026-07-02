from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import solve
from backend.database import init_db, get_all_questions

app = FastAPI(title="AI学习伴侣")

# 允许前端跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 定义请求格式
class SolveRequest(BaseModel):
    question: str

# 服务器启动时自动初始化数据库
@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def home():
    return {"message": "AI学习伴侣后端已启动"}

@app.post("/solve")
def solve_question(req: SolveRequest):
    """接收题目 → 查小题库 → 无缓存则AI解题 → 返回结构化答案"""
    result = solve(req.question)
    return result

@app.get("/questions")
def list_questions():
    """查看已保存的所有题目"""
    return get_all_questions()
