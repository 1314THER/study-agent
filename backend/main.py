from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from backend.solver import solve

app = FastAPI(title="AI学习伴侣")

# 允许前端跨域请求（前后端在不同端口，需要这个）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 定义请求格式：接收一个 question 字段
class SolveRequest(BaseModel):
    question: str

@app.get("/")
def home():
    return {"message": "AI学习伴侣后端已启动"}

@app.post("/solve")
def solve_question(req: SolveRequest):
    """接收题目 → AI三段式解题 → 返回结构化答案"""
    result = solve(req.question)
    return result
