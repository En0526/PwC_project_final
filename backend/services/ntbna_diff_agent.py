"""Agent 2 - NTBNA 本局新聞稿前後差異判讀。"""
from __future__ import annotations

import os
import re

from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)


def generate_ntbna_diff_report(
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
        ai_text = _ai_ntbna_diff(
            added=added,
            removed=removed,
            current_snapshot=current_snapshot,
            api_key=api_key,
            model_name=model_name,
        )
        if ai_text:
            return ai_text

    return _basic_ntbna_diff(
        added=added,
        removed=removed,
        current_items=curr_items,
        current_snapshot=current_snapshot,
        has_previous=bool(previous_snapshot),
    )


def _extract_items(snapshot: str | None) -> list[dict[str, str]]:
    if not snapshot:
        return []
    rows: list[dict[str, str]] = []
    in_list = False
    for line in snapshot.splitlines():
        stripped = line.strip()
        if stripped == "[新聞列表]":
            in_list = True
            continue
        if in_list and stripped.startswith("[") and not re.match(r"^\[\d{4}-\d{2}-\d{2}\]", stripped):
            break
        m = re.match(r"^\[(\d{4}-\d{2}-\d{2})\]\s+(.+?)(?:\s+\|\s+(.+))?$", stripped)
        if m:
            rows.append({"date": m.group(1), "title": m.group(2).strip(), "url": (m.group(3) or "").strip()})
    return rows


def _item_key(item: dict[str, str]) -> str:
    return item.get("url") or f"{item.get('date', '')}|{item.get('title', '')}"


def _extract_field(snapshot: str | None, key: str) -> str:
    if not snapshot:
        return ""
    for line in snapshot.splitlines():
        s = line.strip()
        if s.startswith(f"[{key}]"):
            return s.split("]", 1)[-1].strip()
    return ""


def _basic_ntbna_diff(
    *,
    added: list[dict[str, str]],
    removed: list[dict[str, str]],
    current_items: list[dict[str, str]],
    current_snapshot: str,
    has_previous: bool,
) -> str:
    site = _extract_field(current_snapshot, "站點") or "財政部北區國稅局"
    section = _extract_field(current_snapshot, "區塊") or "本局新聞稿"
    total = _extract_field(current_snapshot, "總筆數")

    lines = [f"{site}更新｜{section}"]
    if total:
        lines.append(f"目前總筆數：{total}")
    lines.append(f"本次新增：{len(added)} 則")
    lines.append("-" * 32)

    if added:
        lines.append("新增新聞：")
        for i, item in enumerate(added[:10], 1):
            lines.append(f"  {i}. [{item['date']}] {item['title']}")
    elif not has_previous:
        lines.append("首次建立基準快照，目前前 10 則：")
        for i, item in enumerate(current_items[:10], 1):
            lines.append(f"  {i}. [{item['date']}] {item['title']}")
    else:
        lines.append("列表有變化，但沒有新增新聞。")

    return "\n".join(lines)


def _ai_ntbna_diff(
    *,
    added: list[dict[str, str]],
    removed: list[dict[str, str]],
    current_snapshot: str,
    api_key: str,
    model_name: str | None = None,
) -> str | None:
    model = effective_gemini_model(model_name)

    site = _extract_field(current_snapshot, "站點") or "財政部北區國稅局"
    section = _extract_field(current_snapshot, "區塊") or "本局新聞稿"
    total = _extract_field(current_snapshot, "總筆數") or "未知"

    added_block = "\n".join([f"[{x['date']}] {x['title']}" for x in added]) or "（無新增）"
    removed_block = "\n".join([f"[{x['date']}] {x['title']}" for x in removed]) or "（無移除）"

    prompt = f"""你是網站通知摘要 Agent，請針對新聞列表前後差異輸出繁體中文通知。
【站點】{site}
【區塊】{section}
【總筆數】{total}
【新增】
{added_block}
【移除】
{removed_block}

請輸出純文字，格式：
1) 第一行：{site}更新｜{section}
2) 第二行：本次新增 N 則、移除 M 則
3) 列出最多 8 則新增（含日期、標題，不要列網址）
4) 有移除就列最多 5 則
5) 最後一句結論（例如：建議查看最新 1-2 則重點）
"""
    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.1,
        max_output_tokens=600,
    )
    return text[:2500] if text else None
