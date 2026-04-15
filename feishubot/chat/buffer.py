# -*- coding: utf-8 -*-
"""消息缓存 - 内存存储，无数据库"""

_messages_by_group: dict = {}  # group_id -> { group_name, messages }


def add_message(group_id: str, group_name: str, msg: dict) -> None:
    if group_id not in _messages_by_group:
        _messages_by_group[group_id] = {"group_name": group_name, "messages": []}
    _messages_by_group[group_id]["messages"].append(msg)


def get_and_clear() -> list:
    result = []
    for group_id, entry in _messages_by_group.items():
        if entry["messages"]:
            result.append({
                "group_id": group_id,
                "group_name": entry["group_name"],
                "messages": entry["messages"].copy(),
            })
        entry["messages"].clear()
    return result


def has_data() -> bool:
    return any(e["messages"] for e in _messages_by_group.values())
