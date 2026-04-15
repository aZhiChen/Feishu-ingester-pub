# -*- coding: utf-8 -*-
"""飞书 tenant_access_token 获取与缓存"""
import time

import requests

from feishubot.config import load_config
from feishubot.log import get_logger

API_BASE = "https://open.feishu.cn/open-apis"
logger = get_logger("feishu.auth")

_access_token_cache = {"token": "", "expires_at": 0}


def get_tenant_access_token() -> str:
    """获取（并缓存）飞书 tenant_access_token。"""
    cfg = (load_config().get("feishu") or {})
    app_id = cfg.get("app_id")
    app_secret = cfg.get("app_secret")
    if not app_id or not app_secret:
        raise ValueError("未配置 app_id 或 app_secret")

    now = int(time.time())
    if _access_token_cache["expires_at"] > now + 60:
        logger.debug("[Auth] 使用缓存 tenant_access_token")
        return _access_token_cache["token"]

    r = requests.post(
        f"{API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data.get('msg')}")

    _access_token_cache["token"] = data["tenant_access_token"]
    _access_token_cache["expires_at"] = now + data.get("expire", 7200) - 300
    logger.info("[Auth] tenant_access_token 刷新成功")
    return _access_token_cache["token"]
