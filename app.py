# -*- coding: utf-8 -*-
"""FeishuBot - 飞书群聊接入端入口"""
from flask import Flask, request

from feishubot.config import load_config
from feishubot.feishu.callback import handle_callback
from feishubot.log import get_logger
from feishubot.scheduler import start_schedules

app = Flask(__name__)
logger = get_logger("app")

if __name__ == "__main__":
    cfg = load_config()
    callback_path = (cfg.get("server") or {}).get("path", "/feishu/callback")
    port = (cfg.get("server") or {}).get("port", 8788)

    @app.before_request
    def log_request():
        if request.path == callback_path:
            logger.info("[Request] %s %s", request.method, callback_path)

    @app.route(callback_path, methods=["POST"])
    def message():
        return handle_callback()

    start_schedules()

    logger.info("[FeishuBot] 飞书群聊接入端已启动 (Python)，端口 %s", port)
    logger.info("[Callback] 回调地址: http://your-domain:%s%s", port, callback_path)
    logger.info("[提示] 请确保应用已开启 im:message.group_msg:readonly 权限，以接收群内所有消息")

    app.run(host="0.0.0.0", port=port, debug=False)
