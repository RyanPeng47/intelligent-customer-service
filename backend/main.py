"""
智能客服系统 - FastAPI 后端主入口
Phase 1 接口: 用户端 (Chat / History / Transfer)
"""

import os
import sys
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

# 确保 backend 包可被导入
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.config import ModelConfig
from backend.database import get_db_connection, init_db
from backend.knowledge_service import ingest_markdown_knowledge, list_knowledge_data
from backend.rag_service import get_ai_response, get_copilot_suggestion

# ============================================================
# FastAPI 初始化
# ============================================================
app = FastAPI(title="智能客服系统 API", version="1.0.0")

# CORS 配置 (允许前端跨域请求)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件 (前端)
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ============================================================
# Pydantic 模型
# ============================================================

class LoginRequest(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    ticket_id: Optional[int] = None
    message: str
    user_id: str = "admin"

class TransferRequest(BaseModel):
    ticket_id: int

class AgentReplyRequest(BaseModel):
    ticket_id: int
    message: str

class CloseTicketRequest(BaseModel):
    ticket_id: int

class RateRequest(BaseModel):
    ticket_id: int
    score: int  # 1-5
    comment: Optional[str] = ""


# ============================================================
# 启动事件: 初始化数据库
# ============================================================

@app.on_event("startup")
def startup_event():
    init_db()
    print("Database initialized")
    print(f"DB Path: {ModelConfig.DB_PATH}")
    print(f"DeepSeek Model: {ModelConfig.DEEPSEEK_MODEL_NAME}")
    print(f"Embedding Model: {ModelConfig.EMBEDDING_MODEL_NAME}")


# ============================================================
# 前端入口
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """返回前端首页"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>前端文件未找到，请确保 frontend/index.html 存在</h1>")


# ============================================================
# Phase 1 接口: 登录
# ============================================================

@app.post("/api/login")
async def login(req: LoginRequest):
    """简单登录校验 (MVP: 硬编码 admin/123456)"""
    if req.username == "admin" and req.password == "123456":
        return {
            "success": True,
            "user_id": "admin",
            "username": "admin",
            "message": "登录成功"
        }
    raise HTTPException(status_code=401, detail="用户名或密码错误")


# ============================================================
# Phase 1 接口: 员工/用户端
# ============================================================

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    用户发送消息，获取 AI 回复
    - 若 ticket_id 为空，自动创建新工单
    - 三级推理引擎: QA -> 意图 -> RAG
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. 如果没有 ticket_id，创建新工单
        ticket_id = req.ticket_id
        if not ticket_id:
            cursor.execute(
                "INSERT INTO tickets (user_id, status) VALUES (?, 'pending_ai')",
                (req.user_id,)
            )
            conn.commit()
            ticket_id = cursor.lastrowid

        # 2. 检查工单是否可用 (不能在已完结的工单中发消息)
        cursor.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")
        if ticket["status"] in ("resolved", "rated"):
            raise HTTPException(status_code=400, detail="该工单已完结，无法继续对话")

        # 3. 存储用户消息
        cursor.execute(
            "INSERT INTO messages (ticket_id, sender, content) VALUES (?, 'user', ?)",
            (ticket_id, req.message)
        )
        conn.commit()

        # 4. 如果当前不是 AI 处理状态 (已转人工)，不再调用 AI
        if ticket["status"] in ("queued", "in_progress"):
            return {
                "ticket_id": ticket_id,
                "reply": None,
                "source": "human",
                "message": "已转人工，等待坐席回复"
            }

        # 5. 调用三级推理引擎
        ai_result = get_ai_response(req.message, ticket_id)

        # 6. 存储 AI 回复
        cursor.execute(
            "INSERT INTO messages (ticket_id, sender, content) VALUES (?, 'ai', ?)",
            (ticket_id, ai_result["reply"])
        )
        conn.commit()

        return {
            "ticket_id": ticket_id,
            "reply": ai_result["reply"],
            "source": ai_result["source"],
            "details": ai_result["details"]
        }

    finally:
        conn.close()


@app.get("/api/tickets/history")
async def get_ticket_history(user_id: str = "admin"):
    """获取用户的历史工单列表"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT t.id, t.status, t.summary, t.created_at, t.updated_at,
                      (SELECT content FROM messages WHERE ticket_id = t.id ORDER BY created_at DESC LIMIT 1) as last_message
               FROM tickets t
               WHERE t.user_id = ?
               ORDER BY t.updated_at DESC""",
            (user_id,)
        )
        tickets = [dict(row) for row in cursor.fetchall()]
        return {"tickets": tickets}
    finally:
        conn.close()


@app.get("/api/messages/{ticket_id}")
async def get_messages(ticket_id: int):
    """获取指定工单的所有消息"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, ticket_id, sender, content, type, created_at FROM messages WHERE ticket_id = ? ORDER BY created_at",
            (ticket_id,)
        )
        messages = [dict(row) for row in cursor.fetchall()]

        # 获取工单状态和用户信息
        cursor.execute("SELECT status, user_id FROM tickets WHERE id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        status = ticket["status"] if ticket else "unknown"
        user_id = ticket["user_id"] if ticket else ""

        return {"messages": messages, "status": status, "user_id": user_id}
    finally:
        conn.close()


@app.post("/api/tickets/transfer")
async def transfer_to_human(req: TransferRequest):
    """用户点击'转人工'，更新工单状态"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM tickets WHERE id = ?", (req.ticket_id,))
        ticket = cursor.fetchone()

        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")
        if ticket["status"] != "pending_ai":
            raise HTTPException(status_code=400, detail="工单状态异常，无法转人工")

        cursor.execute(
            "UPDATE tickets SET status = 'queued', updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), req.ticket_id)
        )
        # 添加系统消息
        cursor.execute(
            "INSERT INTO messages (ticket_id, sender, content) VALUES (?, 'system', '用户已申请转人工服务，等待坐席接入...')",
            (req.ticket_id,)
        )
        conn.commit()
        return {"success": True, "message": "已转接人工，请稍候"}
    finally:
        conn.close()


# ============================================================
# Phase 2 接口: 坐席端 (预留)
# ============================================================

@app.get("/api/agent/tickets")
async def get_agent_tickets(status: Optional[str] = None):
    """坐席获取工单列表 (排除 pending_ai)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if status:
            cursor.execute(
                """SELECT t.id, t.user_id, t.status, t.summary, t.created_at,
                          (SELECT content FROM messages WHERE ticket_id = t.id ORDER BY created_at DESC LIMIT 1) as last_message
                   FROM tickets t WHERE t.status = ? ORDER BY t.created_at DESC""",
                (status,)
            )
        else:
            cursor.execute(
                """SELECT t.id, t.user_id, t.status, t.summary, t.created_at,
                          (SELECT content FROM messages WHERE ticket_id = t.id ORDER BY created_at DESC LIMIT 1) as last_message
                   FROM tickets t WHERE t.status IN ('queued', 'in_progress', 'resolved')
                   ORDER BY CASE t.status WHEN 'queued' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END, t.created_at DESC"""
            )
        tickets = [dict(row) for row in cursor.fetchall()]
        return {"tickets": tickets}
    finally:
        conn.close()


@app.post("/api/agent/pickup")
async def agent_pickup_ticket(req: TransferRequest):
    """坐席接单 (将 queued -> in_progress)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM tickets WHERE id = ?", (req.ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")
        if ticket["status"] != "queued":
            raise HTTPException(status_code=400, detail="工单状态异常")

        cursor.execute(
            "UPDATE tickets SET status = 'in_progress', updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), req.ticket_id)
        )
        cursor.execute(
            "INSERT INTO messages (ticket_id, sender, content) VALUES (?, 'system', '坐席已接入，正在为您服务...')",
            (req.ticket_id,)
        )
        conn.commit()
        return {"success": True, "message": "已接入工单"}
    finally:
        conn.close()


@app.post("/api/agent/reply")
async def agent_reply(req: AgentReplyRequest):
    """坐席发送回复"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM tickets WHERE id = ?", (req.ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")
        if ticket["status"] not in ("in_progress", "queued"):
            raise HTTPException(status_code=400, detail="工单状态异常，无法回复")

        # 如果是 queued 状态，自动变为 in_progress
        if ticket["status"] == "queued":
            cursor.execute(
                "UPDATE tickets SET status = 'in_progress', updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), req.ticket_id)
            )

        cursor.execute(
            "INSERT INTO messages (ticket_id, sender, content) VALUES (?, 'agent', ?)",
            (req.ticket_id, req.message)
        )
        conn.commit()
        return {"success": True, "message": "回复已发送"}
    finally:
        conn.close()


@app.post("/api/agent/close")
async def close_ticket(req: CloseTicketRequest):
    """坐席完结工单"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM tickets WHERE id = ?", (req.ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")

        cursor.execute(
            "UPDATE tickets SET status = 'resolved', updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), req.ticket_id)
        )
        cursor.execute(
            "INSERT INTO messages (ticket_id, sender, content) VALUES (?, 'system', '工单已完结，感谢您的使用。')",
            (req.ticket_id,)
        )
        conn.commit()
        return {"success": True, "message": "工单已完结"}
    finally:
        conn.close()


@app.post("/api/copilot/suggest")
async def copilot_suggest(req: TransferRequest):
    """AI Copilot: 根据工单上下文生成建议回复"""
    suggestion = get_copilot_suggestion(req.ticket_id)
    return {"suggestion": suggestion}


# ============================================================
# Phase 3 接口: 知识库管理
# ============================================================

@app.post("/api/knowledge/upload")
async def upload_knowledge(file: UploadFile = File(...)):
    """上传 Markdown 文档并执行入库流程 (切片 + 向量化 + QA生成)"""
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if not filename.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        result = ingest_markdown_knowledge(filename, file_bytes)
        return {
            "success": True,
            "message": "知识库入库成功",
            **result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"知识库入库失败: {e}")


@app.get("/api/knowledge/list")
async def get_knowledge_list(limit: int = 100):
    """获取知识库内容 (来源汇总 + QA对 + 文档切片)"""
    safe_limit = max(1, min(limit, 500))
    return list_knowledge_data(limit=safe_limit)


# ============================================================
# Phase 4 接口: 质检端
# ============================================================

@app.get("/api/admin/tickets/resolved")
async def get_resolved_tickets():
    """获取已完结工单 (供质检)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT t.id, t.user_id, t.status, t.score, t.summary, t.created_at, t.updated_at,
                      (SELECT COUNT(*) FROM messages WHERE ticket_id = t.id) as message_count
               FROM tickets t WHERE t.status IN ('resolved', 'rated')
               ORDER BY t.updated_at DESC, t.created_at DESC"""
        )
        tickets = [dict(row) for row in cursor.fetchall()]
        return {"tickets": tickets}
    finally:
        conn.close()


@app.post("/api/admin/tickets/rate")
async def rate_ticket(req: RateRequest):
    """质检评分"""
    if not (1 <= req.score <= 5):
        raise HTTPException(status_code=400, detail="评分范围 1-5")
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM tickets WHERE id = ?", (req.ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")
        if ticket["status"] not in ("resolved", "rated"):
            raise HTTPException(status_code=400, detail="仅已完结工单可评分")

        cursor.execute(
            "UPDATE tickets SET score = ?, status = 'rated', summary = ?, updated_at = ? WHERE id = ?",
            (req.score, req.comment, datetime.now().isoformat(), req.ticket_id)
        )
        conn.commit()
        return {"success": True, "message": "评分已提交"}
    finally:
        conn.close()


# ============================================================
# 轮询接口: 获取消息更新
# ============================================================

@app.get("/api/messages/poll/{ticket_id}")
async def poll_messages(ticket_id: int, after_id: int = 0):
    """轮询获取新消息 (after_id 之后的消息)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, ticket_id, sender, content, type, created_at FROM messages WHERE ticket_id = ? AND id > ? ORDER BY created_at",
            (ticket_id, after_id)
        )
        messages = [dict(row) for row in cursor.fetchall()]
        
        # 同时返回工单状态
        cursor.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        ticket = cursor.fetchone()
        status = ticket["status"] if ticket else "unknown"

        return {"messages": messages, "status": status}
    finally:
        conn.close()


# ============================================================
# 运行入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
