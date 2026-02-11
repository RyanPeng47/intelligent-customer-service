"""
知识库处理服务
- Markdown 解码/解析
- 文本切片
- Embedding 入库 (knowledge_vector)
- QA 对生成与入库 (knowledge_qa)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Dict, List

from .config import ModelConfig
from .database import get_db_connection
from .utils import text_to_embedding


def _decode_markdown(file_bytes: bytes) -> str:
    """尽可能兼容常见中文文档编码。"""
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文件编码无法识别，请保存为 UTF-8 后重试")


def _strip_markdown(md: str) -> str:
    """提取纯文本，保留标题和段落语义。"""
    text = md.replace("\r\n", "\n").replace("\r", "\n")
    # 移除代码块，避免把代码作为知识内容写入向量库
    text = re.sub(r"```[\s\S]*?```", "\n", text)
    # 图片 ![alt](url) -> alt
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # 链接 [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # markdown 引用/列表符号清理
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # 过多空行压缩
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _split_sections(md: str) -> List[Dict[str, str]]:
    """
    按 Markdown 标题切分为 section。
    每个 section: {"title": str, "content": str}
    """
    lines = md.split("\n")
    sections: List[Dict[str, str]] = []
    current_title = "文档概述"
    current_lines: List[str] = []

    heading_re = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
    for line in lines:
        m = heading_re.match(line)
        if m:
            content = "\n".join(current_lines).strip()
            if content:
                sections.append({"title": current_title, "content": content})
            current_title = m.group(1).strip() or "未命名章节"
            current_lines = []
            continue
        current_lines.append(line)

    tail = "\n".join(current_lines).strip()
    if tail:
        sections.append({"title": current_title, "content": tail})

    if not sections:
        plain = md.strip()
        if plain:
            sections.append({"title": "文档概述", "content": plain})
    return sections


def _chunk_text(text: str, max_chars: int = 700, overlap: int = 120) -> List[str]:
    """按段落分块，超过长度时做滑动窗口切分。"""
    clean = _strip_markdown(text)
    if not clean:
        return []

    paragraphs = [p.strip() for p in clean.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: List[str] = []
    buffer = ""
    for p in paragraphs:
        candidate = f"{buffer}\n\n{p}".strip() if buffer else p
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            if buffer:
                chunks.append(buffer)
                # 重叠窗口，增强上下文连续性
                tail = buffer[-overlap:] if overlap > 0 else ""
                buffer = f"{tail}\n{p}".strip()
            else:
                # 单段过长时直接硬切
                start = 0
                step = max_chars - overlap if max_chars > overlap else max_chars
                while start < len(p):
                    chunks.append(p[start:start + max_chars])
                    start += max(1, step)
                buffer = ""

    if buffer:
        chunks.append(buffer)
    return chunks


def _build_vector_chunks(markdown_text: str, source: str) -> List[str]:
    """生成写入 knowledge_vector 的文本切片。"""
    sections = _split_sections(markdown_text)
    result: List[str] = []
    for sec in sections:
        section_text = _strip_markdown(sec["content"])
        if not section_text:
            continue
        sub_chunks = _chunk_text(section_text)
        for c in sub_chunks:
            result.append(f"【{sec['title']}】\n{c}")
    return result


def _parse_json_array(text: str):
    """尽量从 LLM 输出中提取 JSON 数组。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []


def _generate_qa_by_llm(markdown_text: str, max_pairs: int = 8) -> List[Dict[str, str]]:
    """用 DeepSeek 从文档生成 QA，失败时抛异常由上层回退。"""
    trimmed = _strip_markdown(markdown_text)
    if not trimmed:
        return []

    # 控制提示词长度，避免长文档超限
    if len(trimmed) > 12000:
        trimmed = trimmed[:12000]

    prompt = f"""你是知识库构建助手。请基于下面文档内容，生成 {max_pairs} 组高质量问答。

要求：
1. 问题必须是用户真实会问的问题，简洁清晰
2. 答案必须严格基于文档内容，不编造
3. 每组包含 question、answer 两个字段
4. 仅输出 JSON 数组，不要输出额外说明

文档内容：
{trimmed}
"""

    client = ModelConfig.get_chat_client()
    resp = client.chat.completions.create(
        model=ModelConfig.DEEPSEEK_MODEL_NAME,
        messages=[
            {"role": "system", "content": "你是严谨的知识库问答构建器，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1800,
        timeout=20,
    )
    content = (resp.choices[0].message.content or "").strip()
    pairs = _parse_json_array(content)

    normalized: List[Dict[str, str]] = []
    for item in pairs:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        a = str(item.get("answer", "")).strip()
        if q and a:
            normalized.append({"question": q, "answer": a})

    return normalized[:max_pairs]


def _generate_qa_fallback(markdown_text: str, max_pairs: int = 8) -> List[Dict[str, str]]:
    """规则回退：从章节标题和段落摘要生成 QA。"""
    sections = _split_sections(markdown_text)
    qa_pairs: List[Dict[str, str]] = []

    for sec in sections:
        title = sec["title"].strip()
        plain = _strip_markdown(sec["content"])
        if len(plain) < 20:
            continue

        answer = plain[:220].strip()
        if len(plain) > 220:
            answer += "..."
        question = f"{title}的主要内容是什么？"
        qa_pairs.append({"question": question, "answer": answer})
        if len(qa_pairs) >= max_pairs:
            break

    if not qa_pairs:
        plain = _strip_markdown(markdown_text)
        if plain:
            qa_pairs.append({
                "question": "这份文档主要讲了什么？",
                "answer": (plain[:220] + "...") if len(plain) > 220 else plain
            })
    return qa_pairs[:max_pairs]


def _generate_qa_pairs(markdown_text: str, max_pairs: int = 8) -> List[Dict[str, str]]:
    """优先 LLM 生成，失败自动回退到规则生成。"""
    try:
        qa = _generate_qa_by_llm(markdown_text, max_pairs=max_pairs)
        if qa:
            return qa
    except Exception:
        pass
    return _generate_qa_fallback(markdown_text, max_pairs=max_pairs)


def ingest_markdown_knowledge(filename: str, file_bytes: bytes) -> Dict[str, int | str]:
    """执行完整入库流程。重复上传同名文件会覆盖旧数据。"""
    markdown_text = _decode_markdown(file_bytes).strip()
    if not markdown_text:
        raise ValueError("Markdown 内容为空")

    source = filename.strip()
    vector_chunks = _build_vector_chunks(markdown_text, source)[:60]
    if not vector_chunks:
        raise ValueError("文档中没有可入库的有效文本")

    qa_pairs = _generate_qa_pairs(markdown_text, max_pairs=8)
    imported_vectors = 0
    imported_qa = 0

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # 同源覆盖，避免重复入库
        cursor.execute("DELETE FROM knowledge_vector WHERE source = ?", (source,))
        cursor.execute("DELETE FROM knowledge_qa WHERE source = ?", (source,))

        for chunk in vector_chunks:
            embedding = text_to_embedding(chunk)
            cursor.execute(
                "INSERT INTO knowledge_vector (content, embedding, source) VALUES (?, ?, ?)",
                (chunk, embedding.astype("float32").tobytes(), source),
            )
            imported_vectors += 1

        for qa in qa_pairs:
            cursor.execute(
                "INSERT INTO knowledge_qa (question, answer, source) VALUES (?, ?, ?)",
                (qa["question"], qa["answer"], source),
            )
            imported_qa += 1

        conn.commit()
        return {
            "source": source,
            "vector_count": imported_vectors,
            "qa_count": imported_qa,
            "updated_at": datetime.now().isoformat(),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_knowledge_data(limit: int = 100) -> Dict[str, List[Dict]]:
    """返回知识库聚合结果，供前端展示。"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1) 来源聚合
        source_map: Dict[str, Dict] = {}

        cursor.execute(
            """SELECT source, COUNT(*) AS vector_count, MAX(created_at) AS vector_updated_at
               FROM knowledge_vector
               GROUP BY source"""
        )
        for row in cursor.fetchall():
            source = row["source"] or "unknown"
            source_map[source] = {
                "source": source,
                "vector_count": row["vector_count"] or 0,
                "qa_count": 0,
                "updated_at": row["vector_updated_at"],
            }

        cursor.execute(
            """SELECT source, COUNT(*) AS qa_count, MAX(created_at) AS qa_updated_at
               FROM knowledge_qa
               GROUP BY source"""
        )
        for row in cursor.fetchall():
            source = row["source"] or "unknown"
            if source not in source_map:
                source_map[source] = {
                    "source": source,
                    "vector_count": 0,
                    "qa_count": 0,
                    "updated_at": row["qa_updated_at"],
                }
            source_map[source]["qa_count"] = row["qa_count"] or 0
            if not source_map[source]["updated_at"] or (
                row["qa_updated_at"] and row["qa_updated_at"] > source_map[source]["updated_at"]
            ):
                source_map[source]["updated_at"] = row["qa_updated_at"]

        sources = sorted(
            source_map.values(),
            key=lambda x: x["updated_at"] or "",
            reverse=True,
        )

        # 2) QA 列表
        cursor.execute(
            """SELECT id, question, answer, source, created_at
               FROM knowledge_qa
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        qa_pairs = [dict(row) for row in cursor.fetchall()]

        # 3) 文档切片列表
        cursor.execute(
            """SELECT id, content, source, created_at
               FROM knowledge_vector
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        vectors = [dict(row) for row in cursor.fetchall()]

        return {
            "sources": sources,
            "qa_pairs": qa_pairs,
            "vectors": vectors,
        }
    finally:
        conn.close()
