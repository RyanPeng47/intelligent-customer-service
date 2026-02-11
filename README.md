# 智能客服系统（Intelligent Customer Service System）

一个基于 FastAPI + 静态前端的 AI 与人工协同客服演示项目。

## 功能概览

- 用户端
  - 与 AI 对话（`QA -> 意图识别 -> RAG`）
  - 一键转人工
  - 历史工单查看
- 坐席端
  - 工单队列（`queued / in_progress / resolved`）
  - 回复用户
  - AI Copilot 辅助回复
  - 完结工单
- 知识库
  - 上传 Markdown 文档
  - 自动切片、向量化、QA 生成
  - 查看 QA 对与文档切片
- 质检端
  - 查看已完结工单
  - 筛选和复盘对话
  - 服务评分

## 技术栈

- 后端：FastAPI、SQLite、OpenAI 兼容客户端
- 前端：HTML / CSS / Vanilla JavaScript
- AI：
  - DeepSeek（对话、意图识别、Copilot）
  - DashScope Embedding（向量化，含本地回退策略）

## 目录结构

```text
backend/                 FastAPI 后端与服务逻辑
frontend/                静态前端页面
scripts/                 冒烟测试与测试数据清理脚本
.output/dev-plan.md      分阶段开发计划与状态
.env.example             环境变量模板
```

## 环境要求

- Python 3.10+（推荐 3.13）
- Windows PowerShell（以下示例命令基于 PowerShell）

## 快速启动

1. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r backend\requirements.txt
```

2. 配置环境变量

```powershell
copy .env.example .env
```

编辑 `.env`，至少配置：

- `DEEPSEEK_API_KEY`
- `DASHSCOPE_API_KEY`

3. 启动后端

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

4. 打开系统

- `http://127.0.0.1:8000/`

## 测试脚本

### 1）全流程冒烟测试

覆盖：登录 -> 知识库上传 -> 用户提问 -> 转人工 -> 坐席处理 -> 完结 -> 质检评分

```powershell
.venv\Scripts\python.exe scripts\full_flow_smoke.py
```

预期结果：`OVERALL: PASS`

### 2）清理冒烟测试数据

仅预览（dry-run）：

```powershell
.venv\Scripts\python.exe scripts\cleanup_smoke_data.py
```

执行清理：

```powershell
.venv\Scripts\python.exe scripts\cleanup_smoke_data.py --apply
```

## 主要接口

### 登录

- `POST /api/login`

### 用户端

- `POST /api/chat`
- `GET /api/tickets/history`
- `POST /api/tickets/transfer`
- `GET /api/messages/{ticket_id}`
- `GET /api/messages/poll/{ticket_id}`

### 坐席端

- `GET /api/agent/tickets`
- `POST /api/agent/pickup`
- `POST /api/agent/reply`
- `POST /api/agent/close`
- `POST /api/copilot/suggest`

### 知识库

- `POST /api/knowledge/upload`
- `GET /api/knowledge/list`

### 质检

- `GET /api/admin/tickets/resolved`
- `POST /api/admin/tickets/rate`

## 说明

- `.env`、`.venv`、本地数据库文件（`*.db`）已在 `.gitignore` 中排除。
- 默认使用本地 SQLite 数据库：`customer_service.db`。
