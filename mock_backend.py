# -*- coding: utf-8 -*-
"""模拟后端大脑 - 用于本地测试"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

PORT = 3000
# 测试任务列表，target_id 需为实际群 chat_id（从接收消息日志中获取）
# 注意：必须运行 FeishuBot（不是 WechatBot）才能正确发送到飞书群
PENDING_TASKS = [
    {
        "task_id": "task_test_001",
        "target_type": "group",
        "target_id": "oc_db5e5ee2a88cf69fd86c4ba7459aa4e1",
        "content": "【测试】FeishuBot 发送成功！这是一条来自模拟后端的群消息。",
    },
    {
        "task_id": "task_test_002",
        "target_type": "group",
        "target_id": "oc_db5e5ee2a88cf69fd86c4ba7459aa4e1",
        "content": "【测试】第二条消息 - 确认 FeishuBot 发送功能正常。",
    },
]


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/chat/batch_upload":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            print("[Mock] 收到 batch_upload:", json.dumps(data, ensure_ascii=False, indent=2))
            self._send_json(200, {"code": 200, "msg": "ok"})
        elif self.path == "/api/bot/ack_task":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            print("[Mock] ack_task:", data)
            self._send_json(200, {"code": 200, "msg": "ok"})
        else:
            self._send_json(404, {"code": 404, "msg": "Not Found"})

    def do_GET(self):
        if self.path == "/api/bot/get_tasks":
            has_task = len(PENDING_TASKS) > 0
            tasks = [PENDING_TASKS.pop(0)] if has_task else []
            data = {"code": 200, "msg": "success", "data": {"has_task": has_task, "tasks": tasks}}
            print("[Mock] get_tasks 返回:", json.dumps(data, ensure_ascii=False, indent=2))
            self._send_json(200, data)
        else:
            self._send_json(404, {"code": 404, "msg": "Not Found"})

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("", PORT), MockHandler)
    print(f"[Mock Backend] 运行在 http://localhost:{PORT}")
    print("  POST /api/chat/batch_upload - 接收消息")
    print("  GET  /api/bot/get_tasks     - 返回测试任务")
    print("  POST /api/bot/ack_task      - 任务回执")
    server.serve_forever()
