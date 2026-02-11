# 智能客服系统 (AI Customer Service System) - 分步开发清单 (Development Plan)

> **文档目的**: 指导系统的分步开发、测试与验收。
> **原则**: 单页面闭环开发（前端+接口+后端），测试通过后再进入下一阶段。
> **状态**: ✅ 已完成（Phase 0-5 全阶段闭环已跑通）

---

## Phase 0: 基础设施搭建 (Infrastructure) ✅ 已完成
1.  **环境配置**:
    - [x] Python 虚拟环境 & 依赖安装 (`fastapi`, `openai`, `numpy` 等)。
    - [x] `.env` 环境变量配置 (DeepSeek & DashScope Key)。
2.  **数据库初始化**:
    - [x] SQLite 建表脚本 (`tickets`, `messages`, `knowledge_qa`, `knowledge_vector`)。
3.  **核心服务封装**:
    - [ ] `config.py`: 模型配置中心 (已创建)。
    - [ ] `rag_service.py`: 封装 LLM 调用、向量计算、意图识别逻辑 (待开发)。

---

## Phase 1: 界面 2 - 员工/用户端 (User Terminal) & 自助问答闭环
> **目标**: 实现用户登录、发起对话、AI 智能回复（QA/意图/RAG）、转人工。这是系统的核心流量入口。

### 1.1 后端开发 (Backend)
- **接口设计**:
    - `POST /api/chat`: 接收用户消息，返回 AI 回复 (流式或非流式)。
    - `GET /api/tickets/history`: 获取当前用户的历史工单列表。
    - `POST /api/tickets/transfer`: 用户点击“转人工”，更新工单状态。
- **逻辑实现**:
    - 实现 `rag_service.get_ai_response(query)`: 包含 QA 检索 -> 意图识别 -> 向量检索 -> LLM 生成。
    - 实现向量检索工具 `utils.py`: 文本转向量 (Qwen API) + Numpy 余弦相似度计算。

### 1.2 前端开发 (Frontend)
- **页面结构**:
    - 左侧：`HistoryWaitList` (历史会话组件)。
    - 中间：`ChatWindow` (对话框组件)，支持 Markdown 渲染。
    - 右上角：功能入口（暂放占位符）。
- **交互逻辑**:
    - 发送消息 -> 调用 `/api/chat` -> 展示 AI 回复 (打字机效果)。
    - 点击“转人工” -> 调用 `/api/tickets/transfer` -> 系统提示“正在为您转接...”。

### 1.3 用户验收测试 (UAT)
- [x] 场景 A: 提问标准问题，是否命中 QA 库？
- [x] 场景 B: 提问模糊/歧义问题，LLM 是否反问引导？
- [x] 场景 C: 提问复杂问题，是否触发 RAG 检索并生成回答？
- [x] 场景 D: 点击转人工，数据库状态是否变更为 `queued`？

---

## Phase 2: 界面 3 - 坐席端 (Agent Terminal) & 人机协作 ✅ 已完成
> **目标**: 实现坐席接单、实时回复用户、AI 辅助回复 (Copilot)。
> **验收结论 (2026-02-11)**: 后端接口、前端联调、全流程回归均通过。

### 2.1 后端开发 (Backend)
- **接口设计**:
    - `GET /api/agent/tickets`: 获取待处理/进行中的工单列表。
    - `POST /api/agent/reply`: 坐席发送回复 (写入消息表)。
    - `POST /api/agent/close`: 完结工单。
    - `POST /api/copilot/suggest`: 坐席点击“AI 辅助”，根据上下文生成建议回复。
- **逻辑实现**:
    - 轮询接口 `/api/messages/poll`: 用于前端定期拉取最新消息（模拟实时性）。

### 2.2 前端开发 (Frontend)
- **页面结构 (Layout B)**:
    - 左栏：`TicketQueue` (待处理/服务中/已完成)。
    - 中栏：`AgentChatWindow` (引用 User 端组件，增加“发送给用户”功能)。
    - 右栏：`CopilotPanel` (意图分析 + 推荐话术 + 知识库匹配结果)。
- **交互逻辑**:
    - 选中工单 -> 加载历史消息。
    - 收到新消息 -> 轮询更新 UI。
    - 点击“AI 辅助” -> 填充输入框。

### 2.3 用户验收测试 (UAT)
- [x] 场景 A: 用户在 Phase 1 界面发消息，坐席端是否刷新可见？
- [x] 场景 B: 坐席回复后，用户端是否同步收到？
- [x] 场景 C: 测试 AI 辅助生成的回复质量。
- [x] 场景 D: 点击完结，工单状态是否变更为 `resolved`，双方无法再发消息？

---

## Phase 3: 界面 5 - 知识库管理 (Knowledge Base) ✅ 已完成
> **目标**: 为 AI 提供“弹药”。实现文档上传、切片、向量化入库。
> **进展 (2026-02-11)**: `POST /api/knowledge/upload`、`GET /api/knowledge/list` 与知识库前端页面已实现并可用，全流程冒烟已通过。

### 3.1 后端开发 (Backend)
- **接口设计**:
    - `POST /api/knowledge/upload`: 上传 `.md` 文件。
    - `GET /api/knowledge/list`: 查看已入库文档/QA对。
- **逻辑实现**:
    - `Markdown` 解析器：提取文本。
    - `Chunking`: 文本切片策略（按标题或固定长度）。
    - `Embedding Pipeline`: 调用 Qwen 向量化 -> 存入 SQLite BLOB。
    - `QA Gen Pipeline`: 调用 DeepSeek 生成 QA 对 -> 存入 QA 表。

### 3.2 前端开发 (Frontend)
- **页面结构**:
    - 上传区域 (Drag & Drop)。
    - 知识库列表 (QA Tab / 文档 Tab)。
- **交互逻辑**:
    - 上传文件 -> 显示进度条 -> 后端异步处理 -> 提示“入库成功”。

### 3.3 用户验收测试 (UAT)
- [x] 场景: 上传一份 `.md` 格式的产品手册，检查数据库 `knowledge_qa` 和 `knowledge_vector` 是否有数据生成。
- [x] 回归测试: 上传知识后，回到 Phase 1 界面提问相关问题，AI 回答是否更准确？

---

## Phase 4: 界面 4 - 质检端 (QA Audit) ✅ 已完成
> **目标**: 对服务质量进行打分和归档查看。
> **进展 (2026-02-11)**: 质检前端页面（筛选+工单列表+对话查看+评分弹窗）已实现，评分接口校验已增强，自动回归通过。

### 4.1 后端开发 (Backend)
- **接口设计**:
    - `GET /api/admin/tickets/resolved`: 获取已完结工单。
    - `POST /api/admin/tickets/rate`: 提交评分。

### 4.2 前端开发 (Frontend)
- **页面结构**:
    - 筛选栏 (按时间/满意度)。
    - 评分弹窗 (5星打分)。

### 4.3 用户验收测试 (UAT)
- [x] 场景: 对一个已完结的工单打分，检查数据库 `score` 字段是否更新。

---

## Phase 5: 界面 1 - 统一登录 (Login) & 整体集成 ✅ 已完成
> **目标**: 串联所有界面，实现权限控制。
> **进展 (2026-02-11)**: 登录页已支持入口选择（用户/坐席/质检/管理员），并基于入口限制可访问视图。

### 5.1 开发内容
- **前端**:
    - 开发 `LoginPage`。
    - 实现简单的路由守卫 (未登录跳转 Login)。
    - 根据登录后选择的入口 (User/Agent/Admin) 跳转不同 Layout。
- **后端**:
    - 简单校验 `admin` / `123456`。

### 5.2 最终验收 (Final QA)
- [x] 完整跑通 "登录 -> 用户提问 -> AI 回复 -> 转人工 -> 坐席接待 -> 完结 -> 质检 -> 知识库更新" 全流程。
- 自动冒烟脚本: `scripts/full_flow_smoke.py`
- 测试数据清理脚本: `scripts/cleanup_smoke_data.py` (默认 dry-run，`--apply` 执行清理)

