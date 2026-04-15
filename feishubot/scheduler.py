# -*- coding: utf-8 -*-
"""定时任务调度 - 批量上报、任务轮询、知识库同步"""
import threading
import time

from feishubot.backend.client import ack_task, batch_upload, get_tasks
from feishubot.chat.buffer import add_message, get_and_clear, has_data
from feishubot.config import load_config
from feishubot.feishu.sender import send_task
from feishubot.log import get_logger
from feishubot.sync.drive import run_drive_sync
from feishubot.sync.wiki import run_wiki_sync

logger = get_logger("scheduler")


def _run_batch_upload():
    if not has_data():
        return
    groups_data = get_and_clear()
    try:
        batch_upload(groups_data)
        logger.info("[BatchUpload] 已上报 %s 个会话", len(groups_data))
    except Exception as e:
        logger.exception("[BatchUpload] 失败: %s", e)
        for g in groups_data:
            for m in g["messages"]:
                add_message(g["group_id"], g["group_name"], m)


def _run_get_tasks():
    try:
        res = get_tasks()
        data = res.get("data", res)
        if not data.get("has_task") or not (data.get("tasks") or []):
            return

        for task in data["tasks"]:
            try:
                send_task(task)
                ack_task(task["task_id"], "success")
                logger.info(
                    "[Send] 已发送任务 %s -> %s:%s",
                    task["task_id"],
                    task.get("target_type"),
                    task.get("target_id"),
                )
            except Exception as e:
                logger.exception("[Send] 任务 %s 失败: %s", task["task_id"], e)
                ack_task(task["task_id"], "fail", str(e))
    except Exception as e:
        if "ECONNREFUSED" not in str(e):
            logger.exception("[GetTasks] 轮询失败: %s", e)


def start_schedules():
    """启动所有后台定时线程。"""
    cfg = load_config()
    schedule = cfg.get("schedule") or {}
    batch_interval = schedule["batch_upload_interval"] / 1000
    task_interval = schedule["get_tasks_interval"] / 1000
    wiki_interval = schedule.get("wiki_sync_interval", 300000) / 1000
    drive_interval = schedule.get("drive_sync_interval", 86400000) / 1000

    def _batch_loop():
        while True:
            time.sleep(batch_interval)
            _run_batch_upload()

    def _task_loop():
        while True:
            time.sleep(task_interval)
            _run_get_tasks()

    def _wiki_loop():
        while True:
            try:
                run_wiki_sync()
            except Exception as e:
                logger.exception("[WikiSync] 轮询异常: %s", e)
            time.sleep(wiki_interval)

    def _drive_loop():
        while True:
            try:
                run_drive_sync()
            except Exception as e:
                logger.exception("[DriveSync] 轮询异常: %s", e)
            time.sleep(drive_interval)

    threading.Thread(target=_batch_loop, daemon=True).start()
    threading.Thread(target=_task_loop, daemon=True).start()

    wiki_cfg = cfg.get("wiki") or {}
    if wiki_cfg.get("enabled", False):
        threading.Thread(target=_wiki_loop, daemon=True).start()
        logger.info(
            "[Schedule] Wiki 同步已启用: 间隔 %ss, space_ids=%s",
            wiki_interval,
            wiki_cfg.get("space_ids", []),
        )

    drive_cfg = cfg.get("drive") or {}
    if drive_cfg.get("enabled", False):
        threading.Thread(target=_drive_loop, daemon=True).start()
        logger.info(
            "[Schedule] Drive 目录同步已启用: 间隔 %ss, folder_tokens=%s",
            drive_interval,
            drive_cfg.get("folder_tokens", []),
        )

    logger.info("[Schedule] 批量上报间隔: %ss, 任务轮询间隔: %ss", batch_interval, task_interval)
