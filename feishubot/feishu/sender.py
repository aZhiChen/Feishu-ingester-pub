# -*- coding: utf-8 -*-
"""消息发送 - 飞书 im.v1.message API"""
import json

import requests

from feishubot.feishu.auth import API_BASE, get_tenant_access_token
from feishubot.log import get_logger

logger = get_logger("feishu.sender")


def send_to_group(chat_id: str, content: str) -> bool:
    """发送到群 - 使用 im.v1.messages API"""
    token = get_tenant_access_token()
    url = f"{API_BASE}/im/v1/messages"
    params = {"receive_id_type": "chat_id"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": content}),
    }
    logger.info("[Sender] send_to_group: chat_id=%s content_len=%s", chat_id, len(content or ""))
    r = requests.post(url, params=params, headers=headers, json=body, timeout=10)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书发送失败: {data.get('msg')} (code={data.get('code')})")
    return True


def send_to_group_with_at(chat_id: str, user_id: str, content: str) -> bool:
    """发送到群 - post 富文本 @某个用户（user_id 由服务端提供）。"""
    token = get_tenant_access_token()
    url = f"{API_BASE}/im/v1/messages"
    params = {"receive_id_type": "chat_id"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    rich_content = {
        "zh_cn": {
            "title": "",
            "content": [[
                {"tag": "at", "user_id": user_id},
                {"tag": "text", "text": f" {content}"},
            ]],
        },
    }
    body = {
        "receive_id": chat_id,
        "msg_type": "post",
        "content": json.dumps(rich_content, ensure_ascii=False),
    }
    logger.info(
        "[Sender] send_to_group_with_at: chat_id=%s user_id=%s content_len=%s",
        chat_id, user_id, len(content or ""),
    )
    r = requests.post(url, params=params, headers=headers, json=body, timeout=10)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书发送失败: {data.get('msg')} (code={data.get('code')})")
    return True


def send_to_person(open_id: str, content: str) -> bool:
    """发送给个人 - receive_id 使用 open_id"""
    token = get_tenant_access_token()
    url = f"{API_BASE}/im/v1/messages"
    params = {"receive_id_type": "open_id"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": content}),
    }
    logger.info("[Sender] send_to_person: open_id=%s content_len=%s", open_id, len(content or ""))
    r = requests.post(url, params=params, headers=headers, json=body, timeout=10)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书发送失败: {data.get('msg')} (code={data.get('code')})")
    return True


def send_task(task: dict) -> bool:
    """根据任务类型分发消息"""
    target_type = task.get("target_type")
    target_id = task.get("target_id")
    content = task.get("content", "")
    task_type = (task.get("task_type") or "message").lower()
    metadata_json = task.get("metadata_json", "")
    metadata = {}
    if metadata_json:
        try:
            metadata = json.loads(metadata_json)
        except (TypeError, json.JSONDecodeError):
            metadata = {}

    if target_type == "group":
        assignee_user_id = str(metadata.get("assignee_user_id") or "").strip()
        if task_type == "reminder" and assignee_user_id:
            return send_to_group_with_at(target_id, assignee_user_id, content)
        return send_to_group(target_id, content)
    if target_type == "person":
        return send_to_person(target_id, content)
    raise ValueError(f"未知 target_type: {target_type}")
