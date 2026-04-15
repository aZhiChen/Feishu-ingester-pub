# FeishuBot Python 版

飞书群聊接入端，参考 WechatBot-python 实现。**支持读取指定群聊的所有消息**，而不仅限于 @ 机器人的消息。

## 核心特性

- **接收群内所有消息**：需在飞书开放平台开启 `im:message.group_msg:readonly` 权限
- 事件订阅：URL 验证 + 消息事件回调
- 批量上报消息到后端
- 轮询任务并发送消息到群/个人

## 安装

```bash
cd FeishuBot-python
pip install -r requirements.txt
```

## 配置

### 1. 创建配置文件

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml 填写飞书配置
```

### 2. 飞书开放平台配置

1. 登录 [飞书开放平台](https://open.feishu.cn/app/)，创建或选择自建应用
2. **凭证与基础信息**：获取 `App ID`、`App Secret`
3. **权限管理**：开启以下权限
   - `im:message.group_msg:readonly` — **接收群内所有消息**（必选，否则只能收到 @ 机器人的消息）
   - `im:message.p2p_msg:readonly` — 接收单聊消息
   - `im:message:send_as_bot` — 发送消息
4. **事件与回调**：
   - 订阅事件：勾选 **接收消息 v2.0**（`im.message.receive_v1`）
   - 请求地址：`http://你的域名或IP:8788/feishu/callback`（需公网可访问）
   - 加密策略：可选配置 `Encrypt Key`，不配置则事件明文推送
5. **机器人**：开启机器人能力，将机器人加入目标群聊

### 3. config.yaml 配置项说明

| 配置项 | 说明 |
|--------|------|
| `backend.base_url` | 后端大脑 API 地址 |
| `feishu.app_id` | 飞书应用 App ID |
| `feishu.app_secret` | 飞书应用 App Secret |
| `feishu.encrypt_key` | 加密密钥（可选，与事件与回调配置一致） |
| `feishu.verification_token` | 校验 Token（可选） |
| `server.port` | 服务端口，默认 8788 |
| `server.path` | 回调路径，默认 `/feishu/callback` |
| `schedule.batch_upload_interval` | 批量上报间隔（毫秒） |
| `schedule.get_tasks_interval` | 任务轮询间隔（毫秒） |

### 4. 环境变量（可选）

可通过环境变量覆盖配置：

- `CONFIG_PATH` — 配置文件路径
- `BACKEND_BASE_URL` — 后端地址
- `FEISHU_APP_ID` — App ID
- `FEISHU_APP_SECRET` — App Secret
- `FEISHU_ENCRYPT_KEY` — 加密密钥
- `FEISHU_VERIFICATION_TOKEN` — 校验 Token
- `BATCH_UPLOAD_INTERVAL` — 批量上报间隔（毫秒）
- `GET_TASKS_INTERVAL` — 任务轮询间隔（毫秒）

## 运行

```bash
# 启动 FeishuBot（默认端口 8788）
python app.py
```

## 日志

- 已内置统一日志模块 `log.py`
- 默认输出到控制台 + 文件 `logs/app.log`
- 日志级别可通过环境变量 `LOG_LEVEL` 控制（默认 `INFO`）
- 日志文件路径可通过环境变量 `FEISHU_BOT_LOG_FILE` 覆盖

## 本地测试

```bash
# 终端 1：启动模拟后端
python mock_backend.py

# 终端 2：启动 FeishuBot
python app.py
```

## 公网访问

飞书事件回调需要公网可访问的 URL。本地开发可使用：

- [ngrok](https://ngrok.com/)
- [localtunnel](https://localtunnel.github.io/www/)
- 云服务器部署

示例（ngrok）：

```bash
ngrok http 8788
# 将生成的 https://xxx.ngrok.io 配置为请求地址：https://xxx.ngrok.io/feishu/callback
```

## 项目结构

```
FeishuBot-python/
├── app.py           # 主入口，Flask 服务 + 定时任务
├── config.py        # 配置加载
├── callback.py      # 飞书事件回调（URL 验证 + 消息解析）
├── crypto_util.py   # 飞书事件加解密与签名校验
├── message_buffer.py # 消息缓存
├── backend.py       # 后端 API 调用
├── sender.py        # 消息发送（飞书 im.v1.messages API）
├── mock_backend.py  # 模拟后端
├── requirements.txt
└── README.md
```

## 与 WechatBot 的差异

| 项目 | WechatBot | FeishuBot |
|------|-----------|------------|
| 平台 | 企业微信 | 飞书 |
| 群消息 | 仅 @ 机器人（aibot） | **可配置为群内所有消息** |
| 权限 | 智能机器人 | `im:message.group_msg:readonly` |
| 回调 | GET 验证 + POST 消息 | POST 统一处理（含 URL 验证） |
| 加密 | 企业微信 AES | 飞书 AES（SHA256 派生密钥） |

## 常见问题

**Q: 收不到群内消息？**  
A: 确认已开启 `im:message.group_msg:readonly` 权限，并重新发布应用版本。

**Q: URL 验证失败？**  
A: 确保请求地址公网可访问，且 1 秒内能返回 `challenge`。若配置了 Encrypt Key，需正确解密。

**Q: 发送消息失败？**  
A: 确保机器人已加入目标群，且拥有 `im:message:send_as_bot` 权限。`target_id` 需为群 `chat_id`（`oc_` 开头）。
