"""
三级推理引擎 (RAG Service)
核心流程: QA精确匹配 -> 意图模糊检测 -> 向量检索RAG回复

调用链路:
1. 用户 Query -> 检索 QA 库 (通过向量相似度)
2. 若 QA 未命中 -> DeepSeek 判断意图是否模糊
3. 若意图模糊 -> 返回引导性反问
4. 若意图清晰 -> 向量检索知识库 -> 拼接上下文 -> DeepSeek 生成回复
"""

from .config import ModelConfig
from .database import get_db_connection
from .utils import text_to_embedding, search_similar_vectors, search_qa_library


# ============================================================
# 提示词模板
# ============================================================

INTENT_DETECTION_PROMPT = """你是一个意图检测助手。请分析用户的问题是否足够清晰，可以被准确理解和回答。

判断标准：
- 如果问题太模糊、太宽泛、缺乏关键信息，则判定为"模糊"
- 如果问题有明确的主题和目的，即使不完美，也判定为"清晰"

请只回复一个 JSON 格式:
{{"is_vague": true/false, "reason": "简短说明原因"}}

用户问题: {query}"""

GUIDED_QUESTION_PROMPT = """你是一个友善的客服助手。用户的问题太模糊了，你需要礼貌地引导用户提供更具体的信息。

用户的原始问题: {query}
模糊原因: {reason}

请生成一个简短的、友善的引导性反问，帮助用户明确需求。不要超过100字。"""

RAG_RESPONSE_PROMPT = """你是一个专业的客服助手。请基于以下参考资料回答用户的问题。

参考资料:
{context}

用户问题: {query}

要求:
1. 回答必须基于参考资料，不要编造信息
2. 如果参考资料不足以回答，请诚实说明
3. 语气友善专业
4. 回答简洁明了"""

GENERAL_CHAT_PROMPT = """你是一个友善专业的客服助手。请回答以下问题。
如果你不确定答案，请诚实告知用户，并建议他们转人工客服获取更准确的帮助。

用户问题: {query}"""

COPILOT_PROMPT = """你是一个坐席辅助AI (Copilot)。请根据以下客户对话历史，生成一个合适的回复建议给坐席参考。

对话历史:
{conversation_history}

参考知识:
{context}

要求:
1. 回复需要专业、有温度、有同理心
2. 优先使用参考知识中的信息
3. 语气自然，像真人客服
请直接输出建议回复内容，不要附加说明。"""


# ============================================================
# 核心推理函数
# ============================================================

def _call_deepseek(prompt: str, system_message: str = "你是一个智能客服助手。") -> str:
    """调用 DeepSeek 模型"""
    try:
        client = ModelConfig.get_chat_client()
        response = client.chat.completions.create(
            model=ModelConfig.DEEPSEEK_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1024,
            timeout=12,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        if "JSON" in system_message or "json" in system_message:
            return '{"is_vague": false, "reason": "模型调用失败，按清晰问题处理"}'
        return "您好，已收到您的问题。当前模型服务繁忙，建议稍后重试或转人工客服。"


def _check_intent_vague(query: str) -> dict:
    """
    意图检测: 判断用户 Query 是否模糊
    返回: {"is_vague": bool, "reason": str}
    """
    q = (query or "").strip()
    q_nospace = "".join(q.split())
    q_len = len(q_nospace)

    # 启发式快速判断（优先）
    vague_patterns = (
        "这个怎么办",
        "那个怎么办",
        "怎么弄",
        "怎么搞",
        "有问题",
        "帮我看看",
        "求助",
    )
    if q_len <= 4:
        return {"is_vague": True, "reason": "问题过短，缺少关键信息"}
    if any(p in q_nospace for p in vague_patterns):
        return {"is_vague": True, "reason": "描述过于泛化，缺少具体场景"}
    if q_len >= 10:
        return {"is_vague": False, "reason": "问题包含较多信息，按清晰问题处理"}

    prompt = INTENT_DETECTION_PROMPT.format(query=query)
    result = _call_deepseek(prompt, system_message="你是一个意图检测分析器，只返回 JSON 格式的结果。")

    # 尝试解析 JSON
    import json
    try:
        # 清理可能的 markdown 代码块标记
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]  # 去掉第一行
            cleaned = cleaned.rsplit("```", 1)[0]  # 去掉末尾
            cleaned = cleaned.strip()
        data = json.loads(cleaned)
        return {"is_vague": data.get("is_vague", False), "reason": data.get("reason", "")}
    except json.JSONDecodeError:
        # 解析失败, 默认认为意图清晰
        return {"is_vague": False, "reason": "无法解析意图检测结果"}


def _generate_guided_question(query: str, reason: str) -> str:
    """生成引导性反问"""
    prompt = GUIDED_QUESTION_PROMPT.format(query=query, reason=reason)
    return _call_deepseek(prompt)


def _generate_rag_response(query: str, context_chunks: list) -> str:
    """基于 RAG 检索结果生成回复"""
    context = "\n---\n".join([
        f"[来源: {chunk['source']}] (相似度: {chunk['similarity']:.2f})\n{chunk['content']}"
        for chunk in context_chunks
    ])
    prompt = RAG_RESPONSE_PROMPT.format(context=context, query=query)
    response = _call_deepseek(prompt)
    if "模型服务繁忙" in response:
        top = context_chunks[0]
        snippet = top["content"].split("\n", 1)[-1].strip()
        if len(snippet) > 180:
            snippet = snippet[:180] + "..."
        return f"根据知识库资料，建议您参考：{snippet}"
    return response


def _generate_general_response(query: str) -> str:
    """无知识库命中时的通用回复"""
    prompt = GENERAL_CHAT_PROMPT.format(query=query)
    return _call_deepseek(prompt)


# ============================================================
# 主入口: 三级推理引擎
# ============================================================

def get_ai_response(query: str, ticket_id: int = None) -> dict:
    """
    三级推理引擎主入口
    
    返回格式:
    {
        "reply": "回复内容",
        "source": "qa" | "guided" | "rag" | "general",
        "details": {} # 额外信息
    }
    """
    conn = get_db_connection()

    try:
        # ====== 第一级: QA 精确匹配 ======
        qa_results = search_qa_library(query, conn, top_k=1, threshold=0.56)
        if qa_results:
            best_match = qa_results[0]
            return {
                "reply": best_match["answer"],
                "source": "qa",
                "details": {
                    "matched_question": best_match["question"],
                    "similarity": best_match["similarity"]
                }
            }

        # 对短问题先做一次模糊检测，避免“这个怎么办”直接落入 RAG
        short_query = len("".join((query or "").split())) <= 8
        if short_query:
            intent_result = _check_intent_vague(query)
            if intent_result["is_vague"]:
                guided_reply = _generate_guided_question(query, intent_result["reason"])
                return {
                    "reply": guided_reply,
                    "source": "guided",
                    "details": {
                        "reason": intent_result["reason"]
                    }
                }

        # ====== 第二级: RAG 向量检索 ======
        # 对于信息量足够的问题，优先检索知识库，减少误判为“模糊问题”
        query_embedding = text_to_embedding(query, prefer_remote=False)
        vector_results = search_similar_vectors(
            query_embedding, conn, top_k=3, threshold=0.3, query_text=query
        )

        if vector_results:
            rag_reply = _generate_rag_response(query, vector_results)
            return {
                "reply": rag_reply,
                "source": "rag",
                "details": {
                    "chunks_used": len(vector_results),
                    "top_similarity": vector_results[0]["similarity"]
                }
            }

        # ====== 第三级: 意图模糊检测 ======
        # 仅在知识库未命中时，再判断是否需要引导反问
        intent_result = _check_intent_vague(query)
        if intent_result["is_vague"]:
            guided_reply = _generate_guided_question(query, intent_result["reason"])
            return {
                "reply": guided_reply,
                "source": "guided",
                "details": {
                    "reason": intent_result["reason"]
                }
            }

        # ====== 兜底: 通用回复 ======
        general_reply = _generate_general_response(query)
        return {
            "reply": general_reply,
            "source": "general",
            "details": {}
        }

    finally:
        conn.close()


def get_copilot_suggestion(ticket_id: int) -> str:
    """
    坐席 AI Copilot: 根据工单历史和知识库生成建议回复
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # 获取工单的对话历史
        cursor.execute(
            "SELECT sender, content, created_at FROM messages WHERE ticket_id = ? ORDER BY created_at",
            (ticket_id,)
        )
        messages = cursor.fetchall()
        
        if not messages:
            return "暂无对话历史，无法生成建议。"

        # 拼接对话历史
        conversation_history = "\n".join([
            f"[{msg['sender']}] {msg['content']}" for msg in messages
        ])

        # 提取最后一条用户消息用于检索
        user_messages = [msg for msg in messages if msg["sender"] == "user"]
        last_user_msg = user_messages[-1]["content"] if user_messages else ""

        # 向量检索相关知识
        context = "暂无匹配知识"
        if last_user_msg:
            query_embedding = text_to_embedding(last_user_msg, prefer_remote=False)
            vector_results = search_similar_vectors(
                query_embedding, conn, top_k=3, threshold=0.28, query_text=last_user_msg
            )
            if vector_results:
                context = "\n---\n".join([
                    f"[{chunk['source']}]\n{chunk['content']}" for chunk in vector_results
                ])

        prompt = COPILOT_PROMPT.format(
            conversation_history=conversation_history,
            context=context
        )
        return _call_deepseek(prompt)

    finally:
        conn.close()
