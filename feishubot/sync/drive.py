# -*- coding: utf-8 -*-
"""飞书云文档目录同步 - 递归轮询指定 folder，拉取文档内容推送到后端"""
from __future__ import annotations

import time

import requests

from feishubot.backend.client import upload_drive_docs
from feishubot.config import load_config
from feishubot.feishu.auth import API_BASE, get_tenant_access_token
from feishubot.log import get_logger

logger = get_logger("sync.drive")

_synced_docs: dict[str, dict[str, str] | str] = {}


def _chunk_docs(docs: list[dict], size: int) -> list[list[dict]]:
    """将文档列表按固定大小分批。"""
    if size < 1:
        size = 10
    return [docs[i : i + size] for i in range(0, len(docs), size)]


def _upload_batch_with_retries(
    root_folder_token: str,
    batch: list[dict],
    *,
    batch_index: int,
    batch_total: int,
    max_attempts: int,
    retry_delay: float,
) -> bool:
    """上传单批文档，带重试。整批无 failed 时返回 True。"""
    last_result: dict | None = None
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = upload_drive_docs(batch, root_folder_token)
            last_result = result
            last_exc = None
            failed = result.get("failed_docs", 0)
            synced = result.get("synced_docs", 0)
            skipped = result.get("skipped_docs", 0)
            code_ok = result.get("code") == 200

            if code_ok and failed == 0:
                logger.info(
                    "[DriveSync] 批次 %d/%d 成功: 本批 %d 篇, synced=%s, skipped=%s",
                    batch_index, batch_total, len(batch), synced, skipped,
                )
                return True

            if code_ok:
                logger.warning(
                    "[DriveSync] 批次 %d/%d 部分失败: synced=%s, skipped=%s, failed=%s (第 %d/%d 次)",
                    batch_index, batch_total, synced, skipped, failed, attempt, max_attempts,
                )
            else:
                logger.error(
                    "[DriveSync] 批次 %d/%d 后端错误: %s (第 %d/%d 次)",
                    batch_index, batch_total, result, attempt, max_attempts,
                )

            if attempt < max_attempts:
                logger.info("[DriveSync] %.1fs 后重试本批…", retry_delay)
                time.sleep(retry_delay)
        except Exception as e:
            last_exc = e
            logger.exception(
                "[DriveSync] 批次 %d/%d 推送异常 (第 %d/%d 次): %s",
                batch_index, batch_total, attempt, max_attempts, e,
            )
            if attempt < max_attempts:
                logger.info("[DriveSync] %.1fs 后重试本批…", retry_delay)
                time.sleep(retry_delay)

    if last_exc is not None:
        logger.error(
            "[DriveSync] 批次 %d/%d 已达最大重试次数，仍异常: %s",
            batch_index, batch_total, last_exc,
        )
    elif last_result is not None:
        logger.error(
            "[DriveSync] 批次 %d/%d 已达最大重试次数，仍失败: %s",
            batch_index, batch_total, last_result,
        )
    return False


def run_drive_sync():
    """轮询飞书云文档目录，发现新增/更新文档后推送到后端。"""
    cfg = load_config()
    drive_cfg = cfg.get("drive") or {}
    if not drive_cfg.get("enabled"):
        return

    raw_tokens = drive_cfg.get("folder_tokens") or []
    if isinstance(raw_tokens, str):
        raw_tokens = [raw_tokens] if raw_tokens else []

    if not raw_tokens:
        logger.info("[DriveSync] 未配置 drive.folder_tokens，跳过")
        return

    for entry in raw_tokens:
        if isinstance(entry, dict):
            folder_token = str(entry.get("token", "")).strip()
            hint_name = str(entry.get("name", "")).strip()
        else:
            folder_token = str(entry).strip()
            hint_name = ""
        if not folder_token:
            continue
        try:
            _sync_one_folder(folder_token, hint_name=hint_name)
        except Exception as e:
            logger.exception("[DriveSync] folder=%s 同步失败: %s", folder_token, e)


def _get_folder_name(folder_token: str) -> str:
    """通过飞书 Drive API 获取文件夹名称；失败时返回空字符串。"""
    meta = _get_drive_node_meta(folder_token, "folder", {})
    name = (meta.get("name") or "").strip()
    if name:
        logger.info("[DriveSync] 根目录名称: %s (token=%s)", name, folder_token)
    return name


def _get_drive_node_meta(
    file_token: str,
    node_type: str,
    meta_cache: dict[str, dict],
) -> dict:
    """GET /drive/v1/files/:token，返回 {name, parent_token}，带缓存。"""
    if not file_token:
        return {}
    cache_key = f"{node_type}:{file_token}"
    if cache_key in meta_cache:
        return meta_cache[cache_key]

    token = get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        def _request_meta(params: dict | None) -> dict:
            r = requests.get(
                f"{API_BASE}/drive/v1/files/{file_token}",
                headers=headers,
                params=params or None,
                timeout=10,
            )
            r.raise_for_status()
            return r.json()

        payload = _request_meta({"type": node_type})
        if payload.get("code") != 0:
            # 不同租户/资源类型对 type 参数兼容性存在差异，失败时再试一次无 type 参数。
            payload = _request_meta({})
            if payload.get("code") != 0:
                logger.warning(
                    "[DriveSync] files/meta 失败: token=%s type=%s payload=%s",
                    file_token, node_type, payload,
                )
                out: dict = {}
                meta_cache[cache_key] = out
                return out

        data = payload.get("data") or {}
        file_obj = data.get("file") or data
        out = {
            "name": str(file_obj.get("name", "") or "").strip(),
            "parent_token": str(file_obj.get("parent_token", "") or "").strip(),
        }
        meta_cache[cache_key] = out
        return out
    except Exception as e:
        logger.warning("[DriveSync] files/meta 异常: token=%s type=%s error=%s", file_token, node_type, e)
        out = {}
        meta_cache[cache_key] = out
        return out


def _resolve_file_display_path(
    doc_token: str,
    doc_name: str,
    *,
    immediate_parent_token: str,
    root_folder_token: str,
    root_display_name: str,
    meta_cache: dict[str, dict],
) -> str:
    """根据 parent_token 链向上解析到根目录，得到与云空间一致的完整展示路径。

    仅依赖列表里的 parent_path 会漏掉根目录名，或在列表层级与真实父子关系不一致时少中间文件夹；
    因此用 API 元数据从文档所在文件夹逐级回溯到 root_folder_token。
    """
    parts: list[str] = [doc_name]
    parent = (immediate_parent_token or "").strip()
    if not parent:
        dm = _get_drive_node_meta(doc_token, "docx", meta_cache)
        parent = (dm.get("parent_token") or "").strip()

    depth = 0
    while parent and parent != root_folder_token and depth < 64:
        depth += 1
        meta = _get_drive_node_meta(parent, "folder", meta_cache)
        pname = (meta.get("name") or "").strip()
        if pname:
            parts.insert(0, pname)
        parent = (meta.get("parent_token") or "").strip()

    rel = "/".join(parts)
    if root_display_name:
        return f"{root_display_name}/{rel}"
    return rel


def _sync_one_folder(root_folder_token: str, *, hint_name: str = ""):
    """同步单个根目录下的所有文档（递归遍历子文件夹）。

    hint_name: config 中预先设置的根目录名称；未设置时自动通过 API 获取。
    """
    # 根目录展示名：用于 file_path 首段（config.name > API 名称 > token）
    root_name = (hint_name or _get_folder_name(root_folder_token) or root_folder_token).strip()
    logger.info("[DriveSync] 根目录: %s (token=%s)", root_name, root_folder_token)
    all_docs: list[dict] = []
    meta_cache: dict[str, dict] = {}
    # parent_path 仅表示「根 folder 以下」的相对路径，最后再与 root_name 拼接，避免漏掉根目录名
    _traverse_folder(
        root_folder_token,
        "",
        all_docs,
        root_display_name=root_name,
        root_folder_token=root_folder_token,
        meta_cache=meta_cache,
    )

    if not all_docs:
        logger.info("[DriveSync] folder=%s 无新增/更新文档", root_folder_token)
        return

    logger.info(
        "[DriveSync] folder=%s 发现 %d 篇新增/更新文档，开始分批推送",
        root_folder_token, len(all_docs),
    )

    drive_cfg = load_config().get("drive") or {}
    batch_size = int(drive_cfg.get("upload_batch_size", 10))
    max_attempts = int(drive_cfg.get("upload_max_retries", 5)) + 1
    retry_delay = float(drive_cfg.get("upload_retry_delay_sec", 1))

    batches = _chunk_docs(all_docs, batch_size)
    batch_total = len(batches)

    for bi, batch in enumerate(batches, start=1):
        logger.info(
            "[DriveSync] 上传批次 %d/%d，本批 %d 篇（每批最多 %d 篇）",
            bi, batch_total, len(batch), batch_size,
        )
        ok = _upload_batch_with_retries(
            root_folder_token,
            batch,
            batch_index=bi,
            batch_total=batch_total,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
        )
        if ok:
            for doc in batch:
                cache_key = f"{root_folder_token}:{doc['token']}"
                _synced_docs[cache_key] = {
                    "modified_time": doc["modified_time"],
                    "file_path": doc.get("file_path", ""),
                }
        else:
            logger.error(
                "[DriveSync] 批次 %d/%d 未成功，本批 %d 篇未写入同步缓存，将随下次轮询重试",
                bi, batch_total, len(batch),
            )


def _traverse_folder(
    folder_token: str,
    parent_path: str,
    out: list[dict],
    *,
    root_folder_token: str,
    root_display_name: str,
    meta_cache: dict[str, dict],
):
    """递归遍历文件夹，收集所有 docx 文档。

    file_path 使用 parent_token 链解析，避免漏根目录名或中间文件夹（与列表 DFS 不一致时）。
    """
    try:
        files = _list_folder_files(folder_token)
    except Exception as e:
        logger.exception(
            "[DriveSync] 拉取文件列表失败: folder=%s error=%s", folder_token, e,
        )
        return

    for f in files:
        ftype = f.get("type", "")
        name = f.get("name", "")

        if ftype == "folder":
            sub_path = f"{parent_path}/{name}" if parent_path else name
            _traverse_folder(
                f.get("token", ""),
                sub_path,
                out,
                root_folder_token=root_folder_token,
                root_display_name=root_display_name,
                meta_cache=meta_cache,
            )
            continue

        if ftype != "docx":
            continue

        token = f.get("token", "")
        modified_time = str(f.get("modified_time", ""))
        immediate_parent = (f.get("parent_token") or folder_token or "").strip()
        file_path = _resolve_file_display_path(
            token,
            name,
            immediate_parent_token=immediate_parent,
            root_folder_token=root_folder_token,
            root_display_name=root_display_name,
            meta_cache=meta_cache,
        )
        if root_display_name and not file_path.startswith(f"{root_display_name}/"):
            file_path = f"{root_display_name}/{file_path.lstrip('/')}"

        # 同步缓存按“配置根目录 + 文档token”维度记录，且包含 file_path，
        # 防止目录链修复后因 modified_time 未变而无法刷新后端引用路径。
        cache_key = f"{root_folder_token}:{token}"
        cached = _synced_docs.get(cache_key)
        if isinstance(cached, dict):
            if (
                cached.get("modified_time") == modified_time
                and str(cached.get("file_path", "")).strip() == file_path
            ):
                continue
        # 兼容旧缓存格式（仅 modified_time 字符串）：不直接跳过，触发一次修复性重上报。

        try:
            content = _get_doc_raw_content(token)
            if not content.strip():
                logger.info(
                    "[DriveSync] 文档内容为空，跳过: token=%s name=%s", token, name,
                )
                continue

            dfs_guess = f"{parent_path}/{name}" if parent_path else name
            api_rel = file_path.replace(f"{root_display_name}/", "", 1) if root_display_name else file_path
            if api_rel.count("/") < dfs_guess.count("/"):
                corrected = f"{root_display_name}/{dfs_guess}" if root_display_name else dfs_guess
                logger.info(
                    "[DriveSync] file_path API 回溯层级不足，改用 DFS 路径: api=%s → dfs=%s",
                    file_path, corrected,
                )
                file_path = corrected
            elif dfs_guess != file_path and dfs_guess.replace(f"{root_display_name}/", "", 1) != api_rel:
                logger.info(
                    "[DriveSync] file_path 已按 parent_token 校正: dfs=%s → api=%s",
                    dfs_guess, file_path,
                )
            out.append({
                "token": token,
                "name": name,
                "content": content,
                "url": f.get("url", ""),
                "file_path": file_path,
                "modified_time": modified_time,
                # 发给后端时保持根 folder_token 一致，便于 source_ref 与项目归属稳定。
                "folder_token": root_folder_token,
            })
            logger.info("[DriveSync] 已拉取文档: name=%s token=%s file_path=%s", name, token, file_path)
        except Exception as e:
            logger.exception(
                "[DriveSync] 拉取文档内容失败: token=%s error=%s", token, e,
            )


def _list_folder_files(folder_token: str) -> list[dict]:
    """分页拉取指定文件夹下所有文件和子文件夹。"""
    token = get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    page_size = (load_config().get("drive") or {}).get("page_size", 100)

    items: list[dict] = []
    page_token = ""

    while True:
        params: dict = {
            "folder_token": folder_token,
            "order_by": "EditedTime",
            "direction": "DESC",
            "page_size": page_size,
        }
        if page_token:
            params["page_token"] = page_token

        r = requests.get(
            f"{API_BASE}/drive/v1/files",
            headers=headers,
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"list files 返回错误: {payload}")

        data = payload.get("data") or {}
        items.extend(data.get("files") or [])

        if not data.get("has_more"):
            break
        page_token = data.get("page_token") or ""
        if not page_token:
            break

    logger.info(
        "[DriveSync] 文件列表加载完成: folder=%s total=%s", folder_token, len(items),
    )
    return items


def _get_doc_raw_content(doc_token: str) -> str:
    """获取文档纯文本内容。"""
    token = get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{API_BASE}/docx/v1/documents/{doc_token}/raw_content",
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"raw_content 返回错误: {payload}")
    data = payload.get("data") or {}
    return data.get("content", "")
