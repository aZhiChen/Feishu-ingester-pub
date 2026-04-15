# -*- coding: utf-8 -*-
"""配置加载"""
import os
from pathlib import Path

import yaml


def load_config():
    """加载 config.yaml，从项目根目录或 CONFIG_PATH 环境变量指定路径"""
    base = Path(__file__).parent.parent
    config_path = base / "config.yaml"
    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        config_path = Path(env_path)

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}，请复制 config.example.yaml 为 config.yaml 并填写")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 环境变量覆盖
    if base_url := os.environ.get("BACKEND_BASE_URL"):
        cfg.setdefault("backend", {})["base_url"] = base_url
    if app_id := os.environ.get("FEISHU_APP_ID"):
        cfg.setdefault("feishu", {})["app_id"] = app_id
    if app_secret := os.environ.get("FEISHU_APP_SECRET"):
        cfg.setdefault("feishu", {})["app_secret"] = app_secret
    if encrypt_key := os.environ.get("FEISHU_ENCRYPT_KEY"):
        cfg.setdefault("feishu", {})["encrypt_key"] = encrypt_key
    if verification_token := os.environ.get("FEISHU_VERIFICATION_TOKEN"):
        cfg.setdefault("feishu", {})["verification_token"] = verification_token
    if batch_interval := os.environ.get("BATCH_UPLOAD_INTERVAL"):
        cfg.setdefault("schedule", {})["batch_upload_interval"] = int(batch_interval)
    if task_interval := os.environ.get("GET_TASKS_INTERVAL"):
        cfg.setdefault("schedule", {})["get_tasks_interval"] = int(task_interval)
    if wiki_spaces := os.environ.get("FEISHU_WIKI_SPACE_IDS"):
        cfg.setdefault("wiki", {})["space_ids"] = [s.strip() for s in wiki_spaces.split(",") if s.strip()]
        cfg["wiki"]["enabled"] = True
    if wiki_interval := os.environ.get("WIKI_SYNC_INTERVAL"):
        cfg.setdefault("schedule", {})["wiki_sync_interval"] = int(wiki_interval)

    # drive（云文档目录）环境变量覆盖
    if drive_folders := os.environ.get("FEISHU_DRIVE_FOLDER_TOKENS"):
        cfg.setdefault("drive", {})["folder_tokens"] = [s.strip() for s in drive_folders.split(",") if s.strip()]
        cfg["drive"]["enabled"] = True
    if drive_interval := os.environ.get("DRIVE_SYNC_INTERVAL"):
        cfg.setdefault("schedule", {})["drive_sync_interval"] = int(drive_interval)

    # schedule 默认值（单位：毫秒）
    cfg.setdefault("schedule", {})
    cfg["schedule"].setdefault("batch_upload_interval", 300000)
    cfg["schedule"].setdefault("get_tasks_interval", 60000)
    cfg["schedule"].setdefault("wiki_sync_interval", 300000)
    cfg["schedule"].setdefault("drive_sync_interval", 86400000)  # 24h

    # wiki 默认值
    cfg.setdefault("wiki", {})
    cfg["wiki"].setdefault("enabled", False)
    cfg["wiki"].setdefault("space_ids", [])
    cfg["wiki"].setdefault("page_size", 50)

    # drive 默认值
    cfg.setdefault("drive", {})
    cfg["drive"].setdefault("enabled", False)
    cfg["drive"].setdefault("folder_tokens", [])
    cfg["drive"].setdefault("page_size", 100)
    cfg["drive"].setdefault("upload_max_retries", 5)
    cfg["drive"].setdefault("upload_retry_delay_sec", 1)
    cfg["drive"].setdefault("upload_batch_size", 10)

    return cfg
