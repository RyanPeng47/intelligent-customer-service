"""
清理冒烟测试数据（默认 dry-run）

规则：
1) 删除知识库里 source 以 smoke_ 开头的数据
2) 删除包含 [SMOKE] 标记消息的工单及其消息

用法：
    .venv\\Scripts\\python.exe scripts/cleanup_smoke_data.py
    .venv\\Scripts\\python.exe scripts/cleanup_smoke_data.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "customer_service.db"


def collect_targets(conn: sqlite3.Connection):
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM knowledge_qa WHERE source LIKE 'smoke_%'")
    qa_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM knowledge_vector WHERE source LIKE 'smoke_%'")
    vec_count = cur.fetchone()[0]

    cur.execute(
        """
        SELECT DISTINCT ticket_id
        FROM messages
        WHERE content LIKE '[SMOKE]%'
        """
    )
    ticket_ids = [row[0] for row in cur.fetchall()]

    if ticket_ids:
        placeholders = ",".join(["?"] * len(ticket_ids))
        cur.execute(f"SELECT COUNT(*) FROM messages WHERE ticket_id IN ({placeholders})", ticket_ids)
        msg_count = cur.fetchone()[0]
    else:
        msg_count = 0

    return {
        "qa_count": qa_count,
        "vec_count": vec_count,
        "ticket_ids": ticket_ids,
        "message_count": msg_count,
        "ticket_count": len(ticket_ids),
    }


def apply_cleanup(conn: sqlite3.Connection, ticket_ids: list[int]):
    cur = conn.cursor()

    cur.execute("DELETE FROM knowledge_qa WHERE source LIKE 'smoke_%'")
    deleted_qa = cur.rowcount

    cur.execute("DELETE FROM knowledge_vector WHERE source LIKE 'smoke_%'")
    deleted_vec = cur.rowcount

    deleted_msgs = 0
    deleted_tickets = 0
    if ticket_ids:
        placeholders = ",".join(["?"] * len(ticket_ids))
        cur.execute(f"DELETE FROM messages WHERE ticket_id IN ({placeholders})", ticket_ids)
        deleted_msgs = cur.rowcount

        cur.execute(f"DELETE FROM tickets WHERE id IN ({placeholders})", ticket_ids)
        deleted_tickets = cur.rowcount

    conn.commit()
    return {
        "deleted_qa": deleted_qa,
        "deleted_vec": deleted_vec,
        "deleted_msgs": deleted_msgs,
        "deleted_tickets": deleted_tickets,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="执行删除（默认仅预览）")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        targets = collect_targets(conn)
        print("=== Smoke Data Preview ===")
        print(f"knowledge_qa (source=smoke_*): {targets['qa_count']}")
        print(f"knowledge_vector (source=smoke_*): {targets['vec_count']}")
        print(f"tickets (with [SMOKE] messages): {targets['ticket_count']}")
        print(f"messages (under those tickets): {targets['message_count']}")
        if targets["ticket_ids"]:
            print(f"ticket_ids: {targets['ticket_ids'][:20]}")

        if not args.apply:
            print("\nDry-run mode. Add --apply to delete these records.")
            return

        result = apply_cleanup(conn, targets["ticket_ids"])
        print("\n=== Cleanup Applied ===")
        print(result)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

