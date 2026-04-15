# -*- coding: utf-8 -*-
"""根据用户问题类型预拉取 FeishuProjectAssistant 结构化数据，供 ask_bot 与 RAG 一并使用。"""
from __future__ import annotations

import json
from typing import Any, Optional

import requests

from feishubot.backend.client import get_backend_base_url
from feishubot.log import get_logger

logger = get_logger("chat.context")


def classify_question(question: str) -> str:
    """返回: projects | reports | reminders | general"""
    qn = (question or "").strip()
    if not qn:
        return "general"
    qnl = qn.lower()

    if any(x in qn for x in ("提醒列表", "有哪些提醒", "什么提醒", "待提醒")):
        return "reminders"
    if "提醒" in qn and any(
        x in qn for x in ("哪些", "列表", "什么", "当前", "有", "几个", "多少", "查看")
    ):
        return "reminders"

    if any(x in qn for x in ("日报", "周报", "报告")) or "report" in qnl:
        return "reports"

    if "项目" in qn and any(
        x in qn
        for x in (
            "哪些", "什么", "列表", "了解", "知道", "认识",
            "有", "几个", "多少", "进行中", "正在",
        )
    ):
        return "projects"
    if any(x in qn for x in ("有哪些项目", "什么项目", "项目列表", "几个项目")):
        return "projects"

    return "general"


def _safe_get_json(url: str, params: Optional[dict] = None, timeout: float = 15) -> Any:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("[QuestionContext] GET 失败 %s: %s", url, e)
        return None


def _truncate(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def build_extra_context(group_id: str, question: str) -> str:
    """按问题类型调用项目管理/报告/提醒 API，拼成可读摘要。"""
    kind = classify_question(question)
    if kind == "general":
        return ""

    base = get_backend_base_url()
    lines: list[str] = []

    if kind == "projects":
        data = _safe_get_json(f"{base}/api/projects")
        lines.append("【项目列表】来源 GET /api/projects")
        if isinstance(data, list):
            if not data:
                lines.append("（暂无项目）")
            for p in data[:40]:
                if not isinstance(p, dict):
                    continue
                lines.append(
                    f"- {p.get('name', '')} | id={p.get('id', '')} | "
                    f"阶段={p.get('phase') or '-'} | 负责人={p.get('owner') or '-'} | "
                    f"状态={p.get('status') or '-'}"
                )
        elif data is not None:
            lines.append(_truncate(json.dumps(data, ensure_ascii=False), 2000))

    elif kind == "reports":
        resolved = _safe_get_json(f"{base}/api/projects/by_group/{group_id}")
        pid = None
        pname = None
        if isinstance(resolved, dict):
            pid = resolved.get("project_id")
            proj = resolved.get("project")
            if isinstance(proj, dict):
                pname = proj.get("name")

        if not pid:
            lines.append("【当前群未关联项目】无法按群限定报告；以下为系统项目列表摘要：")
            plist = _safe_get_json(f"{base}/api/projects")
            if isinstance(plist, list):
                for p in plist[:15]:
                    if isinstance(p, dict):
                        lines.append(f"- {p.get('name', '')} (id={p.get('id', '')})")
        else:
            lines.append(f"【关联项目】{pname or pid} (project_id={pid})")
            for rt, label in (("daily", "日报"), ("weekly", "周报")):
                reps = _safe_get_json(
                    f"{base}/api/projects/{pid}/reports",
                    params={"report_type": rt},
                )
                if not isinstance(reps, list) or not reps:
                    lines.append(f"\n{label}：暂无")
                    continue
                lines.append(f"\n{label}（最近 {min(5, len(reps))} 条）：")
                for rep in reps[:5]:
                    if not isinstance(rep, dict):
                        continue
                    created = rep.get("created_at")
                    lines.append(
                        f"- {created} | {_truncate(rep.get('content') or '', 500)}"
                    )

    elif kind == "reminders":
        resolved = _safe_get_json(f"{base}/api/projects/by_group/{group_id}")
        pid = None
        if isinstance(resolved, dict):
            pid = resolved.get("project_id")
        params = {}
        if pid:
            params["project_id"] = pid
        lines.append("【提醒列表】来源 GET /api/reminders")
        if pid:
            lines.append(f"（已按当前群关联项目过滤 project_id={pid}）")
        else:
            lines.append("（当前群未关联项目，展示全部提醒）")

        rem = _safe_get_json(f"{base}/api/reminders", params=params or None)
        if not isinstance(rem, list):
            lines.append("（拉取失败或无数据）")
        elif not rem:
            lines.append("（暂无提醒）")
        else:
            for r in rem[:20]:
                if not isinstance(r, dict):
                    continue
                lines.append(
                    f"- [{r.get('status', '')}] {r.get('reminder_type', '')} | "
                    f"{_truncate(r.get('content') or '', 200)} | "
                    f"下次触发={r.get('next_trigger_at')}"
                )

    return "\n".join(lines).strip()
