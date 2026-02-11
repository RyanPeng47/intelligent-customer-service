"""
向量工具模块
- 文本转向量 (调用 Qwen text-embedding-v4)
- 余弦相似度计算 (Numpy)
"""

import hashlib
import re
from difflib import SequenceMatcher
import numpy as np
from .config import ModelConfig


def _local_embedding(text: str, dim: int) -> np.ndarray:
    """
    本地回退 embedding:
    使用稳定哈希将文本映射到固定维度向量，避免外部模型不可用时系统中断。
    """
    vec = np.zeros(dim, dtype=np.float32)
    payload = text.encode("utf-8", errors="ignore")
    if not payload:
        return vec

    for idx in range(0, len(payload), 8):
        chunk = payload[idx:idx + 8]
        digest = hashlib.sha256(chunk).digest()
        slot = int.from_bytes(digest[:4], "little", signed=False) % dim
        sign = 1.0 if (digest[4] % 2 == 0) else -1.0
        vec[slot] += sign

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def text_to_embedding(text: str, prefer_remote: bool = True) -> np.ndarray:
    """
    调用 Qwen (DashScope) 将文本转换为向量
    返回: numpy array 形式的 embedding
    """
    dim = max(1, int(getattr(ModelConfig, "EMBEDDING_DIM", 1536) or 1536))
    if not prefer_remote:
        return _local_embedding(text, dim)
    try:
        client = ModelConfig.get_embedding_client()
        response = client.embeddings.create(
            model=ModelConfig.EMBEDDING_MODEL_NAME,
            input=text,
            timeout=20,
        )
        embedding = response.data[0].embedding
        return np.array(embedding, dtype=np.float32)
    except Exception:
        return _local_embedding(text, dim)


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """计算两个向量的余弦相似度"""
    if vec_a is None or vec_b is None:
        return 0.0
    if vec_a.shape != vec_b.shape:
        return 0.0
    dot_product = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot_product / (norm_a * norm_b))


def search_similar_vectors(
    query_embedding: np.ndarray,
    db_connection,
    top_k: int = 3,
    threshold: float = 0.5,
    query_text: str | None = None,
):
    """
    在 knowledge_vector 表中搜索与 query_embedding 最相似的 top_k 条记录
    返回: [(content, similarity_score, source), ...]
    """
    cursor = db_connection.cursor()
    cursor.execute("SELECT id, content, embedding, source FROM knowledge_vector")
    rows = cursor.fetchall()

    if not rows:
        return []

    def _normalize(text: str) -> str:
        return re.sub(r"\s+", "", (text or "").lower())

    def _char_set_score(a: str, b: str) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    query_norm = _normalize(query_text or "")

    results = []
    for row in rows:
        stored_embedding = np.frombuffer(row["embedding"], dtype=np.float32)
        if stored_embedding.size == 0:
            continue
        emb_similarity = cosine_similarity(query_embedding, stored_embedding)
        lexical_similarity = 0.0
        if query_norm:
            content_norm = _normalize(row["content"])
            lexical_similarity = max(
                _char_set_score(query_norm, content_norm),
                SequenceMatcher(None, query_norm, content_norm).ratio(),
            )
        similarity = max(emb_similarity, lexical_similarity)
        if similarity >= threshold:
            results.append({
                "id": row["id"],
                "content": row["content"],
                "similarity": similarity,
                "source": row["source"]
            })

    # 按相似度降序排序，取 top_k
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


def search_qa_library(query: str, db_connection, top_k: int = 1, threshold: float = 0.75):
    """
    在 knowledge_qa 表中搜索与 query 最相似的 QA 对
    通过向量化 query 和 question 来计算相似度
    返回: [(question, answer, similarity), ...] 或空列表
    """
    cursor = db_connection.cursor()
    cursor.execute("SELECT id, question, answer, source FROM knowledge_qa")
    rows = cursor.fetchall()

    if not rows:
        return []

    # 向量化用户 query
    query_embedding = text_to_embedding(query, prefer_remote=False)

    def _normalize(text: str) -> str:
        return re.sub(r"\s+", "", (text or "").lower())

    def _char_set_score(a: str, b: str) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    query_norm = _normalize(query)

    results = []
    for row in rows:
        # 向量化 QA 库中的 question
        q_embedding = text_to_embedding(row["question"], prefer_remote=False)
        emb_similarity = cosine_similarity(query_embedding, q_embedding)
        q_norm = _normalize(row["question"])
        lexical_similarity = max(
            _char_set_score(query_norm, q_norm),
            SequenceMatcher(None, query_norm, q_norm).ratio(),
        )
        similarity = max(emb_similarity, lexical_similarity)
        if similarity >= threshold:
            results.append({
                "id": row["id"],
                "question": row["question"],
                "answer": row["answer"],
                "similarity": similarity,
                "source": row["source"]
            })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]
