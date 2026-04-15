# -*- coding: utf-8 -*-
"""飞书知识库同步 - 拉取 wiki 节点和文档内容，推送到后端"""
import requests

from feishubot.backend.client import upload_wiki_docs
from feishubot.config import load_config
from feishubot.feishu.auth import API_BASE, get_tenant_access_token
from feishubot.log import get_logger

logger = get_logger("sync.wiki")

_synced_docs: dict[str, str] = {}


def run_wiki_sync():
    """轮询飞书知识库，发现新增/更新文档后推送到后端。"""
    cfg = load_config()
    wiki_cfg = cfg.get("wiki") or {}
    if not wiki_cfg.get("enabled"):
        return

    space_ids = wiki_cfg.get("space_ids") or []
    if isinstance(space_ids, str):
        space_ids = [space_ids] if space_ids else []

    if not space_ids:
        logger.info("[WikiSync] 未配置 wiki.space_ids，跳过")
        return

    for space_id in space_ids:
        space_id = str(space_id).strip()
        if not space_id:
            continue
        try:
            _sync_one_space(space_id)
        except Exception as e:
            logger.exception("[WikiSync] space=%s 同步失败: %s", space_id, e)


def _sync_one_space(space_id: str):
    """同步单个知识库。"""
    space_name = _get_space_name(space_id)

    try:
        nodes = _list_space_nodes(space_id)
    except Exception as e:
        logger.exception("[WikiSync] 拉取节点列表失败: space=%s error=%s", space_id, e)
        return

    doc_nodes = [n for n in nodes if n.get("obj_type") == "docx" and n.get("obj_token")]
    logger.info("[WikiSync] space=%s(%s) 扫描到 %s 篇 docx 文档", space_id, space_name, len(doc_nodes))

    nodes_by_token = {n.get("node_token", ""): n for n in nodes if n.get("node_token")}

    new_docs = []
    for node in doc_nodes:
        obj_token = node.get("obj_token", "")
        obj_edit_time = str(node.get("obj_edit_time", ""))
        file_path = _build_file_path(node, nodes_by_token, space_name)

        cache_key = f"{space_id}:{obj_token}"
        cached = _synced_docs.get(cache_key)
        if isinstance(cached, dict):
            if cached.get("obj_edit_time") == obj_edit_time and cached.get("file_path") == file_path:
                continue
        elif cached == obj_edit_time:
            pass  # old format, force re-sync to update file_path

        try:
            content = _get_doc_raw_content(obj_token)
            if not content.strip():
                logger.info("[WikiSync] 文档内容为空，跳过: obj_token=%s", obj_token)
                continue

            new_docs.append({
                "obj_token": obj_token,
                "node_token": node.get("node_token", ""),
                "title": node.get("title", ""),
                "content": content,
                "obj_edit_time": obj_edit_time,
                "space_id": space_id,
                "file_path": file_path,
            })
            logger.info("[WikiSync] 已拉取文档: title=%s file_path=%s obj_token=%s", node.get("title"), file_path, obj_token)
        except Exception as e:
            logger.exception("[WikiSync] 拉取文档内容失败: obj_token=%s error=%s", obj_token, e)

    if not new_docs:
        logger.info("[WikiSync] space=%s 无新增/更新文档", space_id)
        return

    try:
        result = upload_wiki_docs(new_docs, space_id, space_name)
        failed = result.get("failed_docs", 0)
        synced = result.get("synced_docs", 0)
        skipped = result.get("skipped_docs", 0)

        if result.get("code") == 200 and failed == 0:
            for doc in new_docs:
                _synced_docs[f"{space_id}:{doc['obj_token']}"] = {
                    "obj_edit_time": doc["obj_edit_time"],
                    "file_path": doc.get("file_path", ""),
                }
            logger.info("[WikiSync] 全部成功: synced=%s, skipped=%s", synced, skipped)
        elif result.get("code") == 200:
            logger.warning(
                "[WikiSync] 部分失败(下次重试): synced=%s, skipped=%s, failed=%s",
                synced, skipped, failed,
            )
        else:
            logger.error("[WikiSync] 后端返回错误: %s", result)
    except Exception as e:
        logger.exception("[WikiSync] 推送后端失败: %s", e)


def _get_space_name(space_id: str) -> str:
    """获取知识库名称。"""
    token = get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(
            f"{API_BASE}/wiki/v2/spaces/{space_id}",
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") == 0:
            name = (payload.get("data") or {}).get("space", {}).get("name", "")
            if name:
                logger.info("[WikiSync] 知识库名称: %s (space_id=%s)", name, space_id)
                return name
    except Exception as e:
        logger.exception("[WikiSync] 获取知识库名称失败: space_id=%s error=%s", space_id, e)
    return ""


def _list_children(space_id: str, parent_node_token: str | None = None) -> list[dict]:
    """分页拉取某个父节点的直接子节点（parent_node_token=None 时拉取根节点）。"""
    token = get_tenant_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    page_size = (load_config().get("wiki") or {}).get("page_size", 50)
    page_token = ""
    items: list[dict] = []

    while True:
        params: dict = {"page_size": page_size}
        if parent_node_token:
            params["parent_node_token"] = parent_node_token
        if page_token:
            params["page_token"] = page_token

        r = requests.get(
            f"{API_BASE}/wiki/v2/spaces/{space_id}/nodes",
            headers=headers,
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"list nodes 返回错误: {payload}")

        data = payload.get("data") or {}
        items.extend(data.get("items") or [])

        if not data.get("has_more"):
            break
        page_token = data.get("page_token") or ""
        if not page_token:
            break

    return items


def _list_space_nodes(space_id: str) -> list[dict]:
    """递归拉取知识库全部节点（包含所有层级）。"""
    all_nodes: list[dict] = []

    def _recurse(parent_token: str | None):
        children = _list_children(space_id, parent_token)
        for node in children:
            all_nodes.append(node)
            if node.get("has_child"):
                _recurse(node.get("node_token"))

    _recurse(None)
    logger.info("[WikiSync] 节点列表加载完成(递归): space_id=%s total=%s", space_id, len(all_nodes))
    return all_nodes


def _build_file_path(node: dict, nodes_by_token: dict[str, dict], space_name: str) -> str:
    """从节点向上回溯父链，构建完整路径: 空间名/目录1/.../标题。"""
    parts = []
    current = node
    visited = set()
    while current:
        nt = current.get("node_token", "")
        if nt in visited:
            break
        visited.add(nt)
        parts.append(current.get("title", nt))
        parent_token = current.get("parent_node_token", "")
        current = nodes_by_token.get(parent_token) if parent_token else None

    parts.reverse()
    if space_name:
        parts.insert(0, space_name)
    return "/".join(parts)


def _get_doc_raw_content(obj_token: str) -> str:
    """获取文档纯文本内容。"""
    token = get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{API_BASE}/docx/v1/documents/{obj_token}/raw_content",
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"raw_content 返回错误: {payload}")
    data = payload.get("data") or {}
    return data.get("content", "")
