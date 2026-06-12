"""Agent 2 - 中時首頁即時新聞差異判讀。"""
from __future__ import annotations

import os
import re

from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)


def generate_chinatimes_diff_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str | None:
    curr_items = _extract_items(current_snapshot)
    prev_items = _extract_items(previous_snapshot)
    if not curr_items:
        return None

    prev_keys = {_item_key(item) for item in prev_items}
    curr_keys = {_item_key(item) for item in curr_items}
    added = [item for item in curr_items if _item_key(item) not in prev_keys]
    removed = [item for item in prev_items if _item_key(item) not in curr_keys]

    if not added and not removed and previous_snapshot:
        return None

    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if api_key and gemini_sdk_available():
        ai_text = _ai_diff(
            added=added,
            removed=removed,
            api_key=api_key,
            model_name=model_name,
        )
        if ai_text:
            return ai_text

    return _basic_diff(added=added, removed=removed, current_items=curr_items, has_previous=bool(previous_snapshot))


def _extract_items(snapshot: str | None) -> list[dict[str, str]]:
    if not snapshot:
        return []
    rows: list[dict[str, str]] = []
    in_list = False
    for line in snapshot.splitlines():
        s = line.strip()
        if s == "[新聞列表]":
            in_list = True
            continue
        if in_list and s.startswith("[") and not re.match(r"^\[\d{2}:\d{2}\]", s):
            break
        m = re.match(r"^\[(\d{2}:\d{2})\]\s+(.+?)\s+\|\s+(.+?)\s+\|\s+(.+)$", s)
        if m:
            rows.append({"time": m.group(1), "category": m.group(2), "title": m.group(3), "url": m.group(4)})
    return rows


def _item_key(item: dict[str, str]) -> str:
    return item.get("url") or f"{item.get('time', '')}|{item.get('title', '')}"


def _basic_diff(
    *,
    added: list[dict[str, str]],
    removed: list[dict[str, str]],
    current_items: list[dict[str, str]],
    has_previous: bool,
) -> str:
    lines = [
        "中時新聞網更新｜首頁 > 即時新聞",
        f"本次新增：{len(added)} 則",
        "-" * 32,
    ]
    if added:
        lines.append("新增即時新聞：")
        for i, item in enumerate(added[:12], 1):
            lines.append(f"  {i}. [{item['time']}] {item['category']} | {item['title']}")
    elif not has_previous:
        lines.append("首次建立基準快照，目前前 12 則：")
        for i, item in enumerate(current_items[:12], 1):
            lines.append(f"  {i}. [{item['time']}] {item['category']} | {item['title']}")
    else:
        lines.append("列表有變化，但沒有新增即時新聞。")

    return "\n".join(lines)


def _ai_diff(
    *,
    added: list[dict[str, str]],
    removed: list[dict[str, str]],
    api_key: str,
    model_name: str | None = None,
) -> str | None:
    model = effective_gemini_model(model_name)

    added_block = "\n".join([f"[{x['time']}] {x['category']} | {x['title']}" for x in added]) or "（無新增）"
    removed_block = "\n".join([f"[{x['time']}] {x['category']} | {x['title']}" for x in removed]) or "（無移除）"
    prompt = f"""你是新聞列表差異摘要 Agent，輸出繁體中文通知。
【站點】中時新聞網
【區塊】首頁 > 即時新聞
【新增】
{added_block}
【移除】
{removed_block}

格式要求：
1) 第一行：中時新聞網更新｜首頁 > 即時新聞
2) 第二行：本次新增 N 則、移除 M 則
3) 列出最多 10 則新增（含時間、分類、標題，不要列網址）
4) 最後一句簡短結論
輸出純文字。
"""
    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.1,
        max_output_tokens=700,
    )
    return text[:2600] if text else None
