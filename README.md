# Intelligent Customer Service System

An AI + human collaborative customer service demo built with FastAPI and a static frontend.

## What this project includes

- User terminal:
  - Chat with AI (`QA -> intent -> RAG`)
  - Transfer to human agent
  - View ticket history
- Agent terminal:
  - Ticket queue (`queued / in_progress / resolved`)
  - Reply to users
  - AI Copilot suggestion
  - Close ticket
- Knowledge base:
  - Upload Markdown documents
  - Auto chunk + embedding + QA generation
  - View QA pairs and vector chunks
- QA audit terminal:
  - View resolved tickets
  - Filter and review conversations
  - Rate service quality

## Tech stack

- Backend: FastAPI, SQLite, OpenAI-compatible API clients
- Frontend: HTML/CSS/Vanilla JavaScript
- AI:
  - DeepSeek for chat/intent/copilot
  - DashScope embedding model for vectorization (with local fallback)

## Project structure

```text
backend/                 FastAPI app and services
frontend/                Static web UI
scripts/                 Smoke test and cleanup scripts
.output/dev-plan.md      Development and phase status
.env.example             Environment variable template
```

## Prerequisites

- Python 3.10+ (recommended: 3.13)
- Windows PowerShell (commands below use PowerShell syntax)

## Quick start

1. Create venv and install dependencies

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r backend\requirements.txt
```

2. Configure environment variables

```powershell
copy .env.example .env
```

Edit `.env` and set:

- `DEEPSEEK_API_KEY`
- `DASHSCOPE_API_KEY`

3. Start backend

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

4. Open the app

- `http://127.0.0.1:8000/`

## Test scripts

### 1) End-to-end smoke test

Runs login -> knowledge upload -> user chat -> transfer -> agent handling -> close -> audit rating.

```powershell
.venv\Scripts\python.exe scripts\full_flow_smoke.py
```

Expected: `OVERALL: PASS`

### 2) Cleanup smoke data

Preview only (dry-run):

```powershell
.venv\Scripts\python.exe scripts\cleanup_smoke_data.py
```

Apply cleanup:

```powershell
.venv\Scripts\python.exe scripts\cleanup_smoke_data.py --apply
```

## Main API endpoints

### Auth

- `POST /api/login`

### User terminal

- `POST /api/chat`
- `GET /api/tickets/history`
- `POST /api/tickets/transfer`
- `GET /api/messages/{ticket_id}`
- `GET /api/messages/poll/{ticket_id}`

### Agent terminal

- `GET /api/agent/tickets`
- `POST /api/agent/pickup`
- `POST /api/agent/reply`
- `POST /api/agent/close`
- `POST /api/copilot/suggest`

### Knowledge base

- `POST /api/knowledge/upload`
- `GET /api/knowledge/list`

### QA audit

- `GET /api/admin/tickets/resolved`
- `POST /api/admin/tickets/rate`

## Notes

- `.env`, `.venv`, and local databases (`*.db`) are excluded by `.gitignore`.
- This project stores data in local SQLite (`customer_service.db`) by default.

