"""
全流程冒烟测试脚本
覆盖:
1) 登录接口
2) 知识库上传与列表
3) 用户发消息/转人工
4) 坐席接单/回复/完结
5) 质检评分

运行:
    .venv\\Scripts\\python.exe scripts/full_flow_smoke.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from backend.main import app


def assert_ok(name: str, cond: bool, detail: str = ""):
    if not cond:
        raise AssertionError(f"[FAIL] {name}: {detail}")
    print(f"[PASS] {name}{' | ' + detail if detail else ''}")


def main():
    source = f"smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    md = b"""# \xe9\x80\x80\xe6\xac\xbe\xe8\xaf\xb4\xe6\x98\x8e\n\n\xe9\x80\x80\xe6\xac\xbe\xe9\x80\x9a\xe5\xb8\xb8\xe5\x9c\xa8 3-5 \xe4\xb8\xaa\xe5\xb7\xa5\xe4\xbd\x9c\xe6\x97\xa5\xe5\x88\xb0\xe8\xb4\xa6\xe3\x80\x82\n\n## \xe6\x8f\x90\xe4\xba\xa4\xe6\x9d\xa1\xe4\xbb\xb6\n\n\xe9\x9c\x80\xe6\x8f\x90\xe4\xbe\x9b\xe8\xae\xa2\xe5\x8d\x95\xe5\x8f\xb7\xe4\xb8\x8e\xe6\x94\xaf\xe4\xbb\x98\xe5\x87\xad\xe8\xaf\x81\xe3\x80\x82\n"""

    with TestClient(app) as client:
        # 1) 登录
        r = client.post("/api/login", json={"username": "admin", "password": "123456"})
        assert_ok("登录接口", r.status_code == 200, str(r.json()))

        # 2) 知识库上传
        files = {"file": (source, md, "text/markdown")}
        r = client.post("/api/knowledge/upload", files=files)
        body = r.json()
        assert_ok("知识库上传", r.status_code == 200, str(body))
        assert_ok("知识库生成切片", body.get("vector_count", 0) > 0, str(body))
        assert_ok("知识库生成QA", body.get("qa_count", 0) > 0, str(body))

        r = client.get("/api/knowledge/list?limit=50")
        body = r.json()
        sources = [x.get("source") for x in body.get("sources", [])]
        assert_ok("知识库列表可见", source in sources, str(sources[:5]))

        # 3) 用户创建会话
        r = client.post("/api/chat", json={"user_id": "admin", "message": "[SMOKE] 退款多久到账？"})
        body = r.json()
        assert_ok("用户发消息", r.status_code == 200, str(body))
        ticket_id = body["ticket_id"]

        # 4) 转人工
        r = client.post("/api/tickets/transfer", json={"ticket_id": ticket_id})
        assert_ok("转人工", r.status_code == 200, str(r.json()))

        # 5) 坐席流程
        r = client.post("/api/agent/pickup", json={"ticket_id": ticket_id})
        assert_ok("坐席接入", r.status_code == 200, str(r.json()))

        r = client.post("/api/agent/reply", json={"ticket_id": ticket_id, "message": "[SMOKE] 您好，这里是客服，已为您处理。"})
        assert_ok("坐席回复", r.status_code == 200, str(r.json()))

        r = client.post("/api/copilot/suggest", json={"ticket_id": ticket_id})
        body = r.json()
        assert_ok("Copilot 返回", r.status_code == 200 and bool(body.get("suggestion")), str(body))

        r = client.post("/api/agent/close", json={"ticket_id": ticket_id})
        assert_ok("工单完结", r.status_code == 200, str(r.json()))

        # 6) 质检评分
        r = client.post("/api/admin/tickets/rate", json={"ticket_id": ticket_id, "score": 5, "comment": "[SMOKE] 流程顺畅"})
        assert_ok("质检评分", r.status_code == 200, str(r.json()))

        # 7) 验证评分结果
        r = client.get("/api/admin/tickets/resolved")
        items = r.json().get("tickets", [])
        target = next((x for x in items if x["id"] == ticket_id), None)
        assert_ok("评分结果可查", bool(target), f"ticket_id={ticket_id}")
        assert_ok("评分写入成功", target.get("score") == 5, str(target))

    print("\nOVERALL: PASS")


if __name__ == "__main__":
    main()
