# -*- coding: utf-8 -*-
"""与后端大脑的 API 对接"""
import time

import requests

from feishubot.config import load_config
from feishubot.log import get_logger

logger = get_logger("backend.client")


def get_backend_base_url() -> str:
    cfg = load_config()
    return (cfg.get("backend") or {}).get("base_url", "http://localhost:3000").rstrip("/")


def batch_upload(groups_data: list) -> dict:
    """POST /api/chat/batch_upload"""
    url = f"{get_backend_base_url()}/api/chat/batch_upload"
    body = {
        "timestamp": int(time.time()),
        "groups_data": groups_data,
    }
    logger.info("[Backend] batch_upload: sessions=%s", len(groups_data))
    r = requests.post(url, json=body, timeout=10)
    return r.json()


def get_tasks() -> dict:
    """GET /api/bot/get_tasks"""
    url = f"{get_backend_base_url()}/api/bot/get_tasks"
    logger.debug("[Backend] get_tasks from %s", url)
    r = requests.get(url, timeout=10)
    return r.json()


def ack_task(task_id: str, status: str, error_msg: str = "") -> dict:
    """POST /api/bot/ack_task"""
    url = f"{get_backend_base_url()}/api/bot/ack_task"
    body = {"task_id": task_id, "status": status, "error_msg": error_msg}
    logger.info("[Backend] ack_task: task_id=%s status=%s", task_id, status)
    r = requests.post(url, json=body, timeout=10)
    return r.json()


def upload_wiki_docs(docs: list, space_id: str = "", space_name: str = "") -> dict:
    """POST /api/knowledge/wiki/upload - 推送 wiki 文档到后端"""
    url = f"{get_backend_base_url()}/api/knowledge/wiki/upload"
    body = {
        "space_id": space_id,
        "space_name": space_name,
        "docs": docs,
    }
    logger.info("[Backend] upload_wiki_docs: space=%s docs=%s", space_id, len(docs))
    # 大批量文档 + 后端嵌入索引可能超过 60s，避免 Read timed out
    r = requests.post(url, json=body, timeout=(15, 600))
    return r.json()


def upload_drive_docs(docs: list, folder_token: str = "") -> dict:
    """POST /api/knowledge/drive/upload - 推送云文档到后端"""
    url = f"{get_backend_base_url()}/api/knowledge/drive/upload"
    body = {
        "folder_token": folder_token,
        "docs": docs,
    }
    logger.info("[Backend] upload_drive_docs: folder=%s docs=%s", folder_token, len(docs))
    # 递归目录可能一次推送多篇 docx，后端逐篇切块+embedding 易超 60s
    r = requests.post(url, json=body, timeout=(15, 600))
    return r.json()


def ask_bot(group_id: str, question: str, sender_id: str = "",
            sender_name: str = "", message_id: str = "",
            extra_context: str = "") -> dict:
    """POST /api/chat/ask_bot - 获取 LLM 对 @bot 提及的回复"""
    url = f"{get_backend_base_url()}/api/chat/ask_bot"
    body = {
        "group_id": group_id,
        "question": question,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "message_id": message_id,
    }
    if extra_context and extra_context.strip():
        body["extra_context"] = extra_context.strip()
    logger.info("[Backend] ask_bot: group_id=%s question_len=%s", group_id, len(question or ""))
    r = requests.post(url, json=body, timeout=120)
    return r.json()
