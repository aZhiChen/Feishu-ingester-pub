# -*- coding: utf-8 -*-
"""飞书事件回调 - URL 验证与消息接收"""
import json
import re
import threading
from datetime import datetime

import requests
from flask import Response, request

from feishubot.chat.buffer import add_message
from feishubot.config import load_config
from feishubot.feishu.auth import API_BASE, get_tenant_access_token
from feishubot.feishu.crypto import decrypt_event, verify_signature
from feishubot.log import get_logger

logger = get_logger("feishu.callback")


_user_name_cache = {}


def _get_feishu_config():
    return (load_config().get("feishu") or {})


def _get_raw_body():
    """获取原始请求体（用于签名校验）"""
    return request.get_data(as_text=True) or ""


def _parse_body(body_text: str) -> dict:
    try:
        return json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        return {}


def _decrypt_if_needed(body: dict) -> dict:
    """若配置了 encrypt_key，则解密后解析"""
    encrypt_key = _get_feishu_config().get("encrypt_key")
    if not encrypt_key:
        return body

    enc = body.get("encrypt")
    if not enc:
        return body

    plain = decrypt_event(encrypt_key, enc)
    return _parse_body(plain)


def _verify_request(body_text: str) -> bool:
    """校验请求签名（配置了 encrypt_key 时）"""
    encrypt_key = _get_feishu_config().get("encrypt_key")
    if not encrypt_key:
        return True

    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")
    if not all([timestamp, nonce, signature]):
        return False

    return verify_signature(timestamp, nonce, encrypt_key, body_text, signature)


def _json_response(data: dict, status: int = 200):
    """返回 JSON 响应，飞书要求必须返回合法 JSON"""
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        mimetype="application/json; charset=utf-8",
    )


def _resolve_sender_identity(sender: dict) -> tuple[str, str]:
    """Extract sender id and its id_type from callback payload."""
    sender_id_obj = sender.get("sender_id", {}) or {}
    if sender_id_obj.get("user_id"):
        return sender_id_obj["user_id"], "user_id"
    if sender_id_obj.get("open_id"):
        return sender_id_obj["open_id"], "open_id"
    if sender_id_obj.get("union_id"):
        return sender_id_obj["union_id"], "union_id"
    return "unknown", "user_id"


def _fetch_user_name(user_id: str, id_type: str) -> str:
    """Fetch user display name from Feishu contact API with cache."""
    if not user_id or user_id == "unknown":
        return ""
    cache_key = f"{id_type}:{user_id}"
    if cache_key in _user_name_cache:
        return _user_name_cache[cache_key]

    try:
        token = get_tenant_access_token()
        r = requests.get(
            f"{API_BASE}/contact/v3/users/{user_id}",
            params={"user_id_type": id_type},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        data = r.json()
        if data.get("code") == 0:
            user = (data.get("data") or {}).get("user", {}) or {}
            name = (
                str(user.get("name") or user.get("en_name") or user_id).strip()
            )
            _user_name_cache[cache_key] = name
            return name
        logger.warning(
            "[Callback] 获取用户名称失败 user_id=%s id_type=%s code=%s msg=%s",
            user_id, id_type, data.get("code"), data.get("msg"),
        )
    except Exception as e:
        logger.warning("[Callback] 查询用户姓名异常 user_id=%s err=%s", user_id, e)
    return ""


def _resolve_sender_name(sender: dict, sender_id: str, sender_id_type: str, mentions: list) -> str:
    """Resolve sender name from event payload first, then contact API."""
    direct_name = (
        sender.get("name")
        or sender.get("sender_name")
        or sender.get("display_name")
        or sender.get("name_cn")
    )
    if direct_name:
        name = str(direct_name).strip()
        logger.info(
            "[Callback] sender_name resolved via payload: sender_id=%s name=%s",
            sender_id, name,
        )
        return name

    sender_id_obj = sender.get("sender_id", {}) or {}
    for key in ("name", "display_name"):
        if sender_id_obj.get(key):
            name = str(sender_id_obj.get(key)).strip()
            logger.info(
                "[Callback] sender_name resolved via sender_id.%s: sender_id=%s name=%s",
                key, sender_id, name,
            )
            return name

    for m in mentions or []:
        m_id = m.get("id", {}) or {}
        if (
            m.get("key") == sender_id
            or m_id.get("user_id") == sender_id
            or m_id.get("open_id") == sender_id
            or m_id.get("union_id") == sender_id
        ):
            name = str(m.get("name") or sender_id).strip()
            logger.info(
                "[Callback] sender_name resolved via mentions: sender_id=%s name=%s",
                sender_id, name,
            )
            return name

    fetched = _fetch_user_name(sender_id, sender_id_type)
    if fetched:
        logger.info(
            "[Callback] sender_name resolved via contact_api: sender_id=%s id_type=%s name=%s",
            sender_id, sender_id_type, fetched,
        )
        return fetched

    logger.warning(
        "[Callback] sender_name fallback to sender_id: sender_id=%s id_type=%s",
        sender_id, sender_id_type,
    )
    return sender_id


def handle_callback():
    """POST - 飞书事件回调（URL 验证 + 消息事件）"""
    body_text = _get_raw_body()
    if not body_text:
        logger.warning("[Callback] 错误: 请求体为空")
        return _json_response({"error": "no_body"}, 400)

    body = _parse_body(body_text)
    try:
        body = _decrypt_if_needed(body)
    except Exception as e:
        logger.exception("[Callback] 解密失败: %s", e)
        return _json_response({"error": "decrypt_failed"}, 400)

    # URL 验证：飞书要求 1 秒内返回 challenge，优先处理且不校验签名
    challenge = body.get("challenge", "")
    if body.get("type") == "url_verification":
        logger.info("[Callback] URL 验证请求, challenge_len=%s", len(challenge))
        return _json_response({"challenge": challenge})

    # 容错：JSON 解析失败时，尝试从原始 body 提取 challenge（如 curl 格式异常）
    if not challenge and "url_verification" in body_text and "challenge" in body_text:
        m = re.search(r'challenge["\']?\s*[:=]\s*["\']?([^"\'}\s]+)', body_text)
        if m:
            challenge = m.group(1)
            logger.info("[Callback] URL 验证(容错解析), challenge=%s", challenge)
            return _json_response({"challenge": challenge})

    # 事件推送：需校验签名
    if not _verify_request(body_text):
        logger.warning("[Callback] 签名校验失败")
        return _json_response({"error": "invalid_signature"}, 403)

    # 事件推送
    schema = body.get("schema", "")
    header = body.get("header", {})
    event_type = header.get("event_type", "")
    event = body.get("event", {})
    logger.debug("[Callback] 收到事件: schema=%s type=%s", schema, event_type)

    if event_type != "im.message.receive_v1":
        return _json_response({"ok": True})

    # 解析消息
    sender = event.get("sender", {})
    sender_id, sender_id_type = _resolve_sender_identity(sender)

    message = event.get("message", {})
    chat_id = message.get("chat_id", "")
    chat_type = message.get("chat_type", "group")  # group, p2p
    message_type = message.get("message_type", "")
    content_str = message.get("content", "{}")
    message_id = message.get("message_id", "") or f"msg_{int(datetime.now().timestamp() * 1000)}"

    # 忽略机器人自己发的消息
    if sender.get("sender_type") == "app":
        return _json_response({"ok": True})

    group_id = chat_id if chat_type in ("group", "topic_group") else sender_id
    group_name = f"群聊-{chat_id}" if chat_type in ("group", "topic_group") else f"单聊-{sender_id}"

    content = ""
    try:
        content_obj = json.loads(content_str) if isinstance(content_str, str) else content_str
        if message_type == "text" and content_obj.get("text"):
            content = content_obj["text"]
        elif message_type == "post":
            content = "[富文本消息]"
        elif message_type == "image":
            content = "[图片]"
        elif message_type == "file":
            content = "[文件]"
        elif message_type == "audio":
            content = "[语音]"
        elif message_type == "media":
            content = "[视频]"
        elif message_type == "sticker":
            content = "[表情]"
        else:
            content = f"[{message_type}]"
    except (json.JSONDecodeError, TypeError):
        content = "[未知消息]"

    if content:
        now = datetime.now()
        send_time = now.strftime("%Y-%m-%d %H:%M:%S")
        mentions = message.get("mentions", [])
        sender_name = _resolve_sender_name(sender, sender_id, sender_id_type, mentions)

        add_message(group_id, group_name, {
            "msg_id": message.get("message_id", message_id),
            "sender_id": sender_id,
            "sender_name": sender_name,
            "content": content,
            "send_time": send_time,
        })
        logger.info("[Callback] 收到消息: %s | %s: %s", group_name, sender_name, content[:50])

        bot_mentioned, clean_question = _check_bot_mention(content, mentions)
        if bot_mentioned and clean_question.strip():
            threading.Thread(
                target=_handle_bot_mention,
                args=(group_id, clean_question, sender_id, sender_name,
                      message.get("message_id", message_id)),
                daemon=True,
            ).start()

    return _json_response({"ok": True})


_bot_open_id_cache = {"open_id": "", "fetched": False}


def _get_bot_open_id() -> str:
    """获取并缓存机器人自身 open_id（通过 GET /bot/v3/info）。"""
    if _bot_open_id_cache["fetched"]:
        return _bot_open_id_cache["open_id"]

    try:
        token = get_tenant_access_token()
        r = requests.get(
            f"{API_BASE}/bot/v3/info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        data = r.json()
        if data.get("code") == 0:
            open_id = data.get("bot", {}).get("open_id", "")
            _bot_open_id_cache["open_id"] = open_id
            _bot_open_id_cache["fetched"] = True
            logger.info("[BotMention] 获取到机器人 open_id: %s", open_id)
            return open_id
    except Exception as e:
        logger.exception("[BotMention] 获取机器人 open_id 失败: %s", e)

    _bot_open_id_cache["fetched"] = True
    return ""


def _check_bot_mention(content: str, mentions: list) -> tuple:
    """判断消息是否 @了机器人，并返回 (is_mentioned, cleaned_question)。

    飞书 mention 格式：content 中含 ``@_user_1`` 占位符，
    mentions 数组将每个 key 映射到 id.open_id，与机器人自身 open_id 比对。
    """
    if not mentions:
        return False, content

    bot_open_id = _get_bot_open_id()
    bot_mentioned = False

    for m in mentions:
        mention_id = m.get("id", {})
        mention_open_id = mention_id.get("open_id", "")

        is_bot = bool(bot_open_id and mention_open_id == bot_open_id)
        if not is_bot:
            cfg = _get_feishu_config()
            app_id = cfg.get("app_id", "")
            if app_id and mention_id.get("app_id") == app_id:
                is_bot = True

        if is_bot:
            bot_mentioned = True
            key = m.get("key", "")
            if key:
                content = content.replace(key, "")
            break

    content = content.strip()
    return bot_mentioned, content


def _handle_bot_mention(group_id: str, question: str, sender_id: str,
                        sender_name: str, message_id: str):
    """后台线程：调用后端 ask_bot 接口，然后向群发送回复。"""
    from feishubot.backend.client import ask_bot
    from feishubot.chat.context import build_extra_context, classify_question
    from feishubot.feishu.sender import send_to_group

    try:
        kind = classify_question(question)
        if kind != "general":
            logger.info("[BotMention] 问题类型=%s，预拉取结构化数据", kind)
        extra = build_extra_context(group_id, question)
        logger.info("[BotMention] 处理 @bot 提问: %s...", question[:60])
        result = ask_bot(
            group_id, question, sender_id, sender_name, message_id,
            extra_context=extra,
        )
        reply = result.get("reply", "") or "抱歉，暂时无法回答这个问题。"
        send_to_group(group_id, reply)
        logger.info("[BotMention] 已回复群 %s: %s...", group_id, reply[:60])
    except Exception as e:
        logger.exception("[BotMention] 回复失败: %s", e)
