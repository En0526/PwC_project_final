"""Agent 2 - MOPS 即時重大資訊差異判讀與摘要。"""
from __future__ import annotations

import os
import re

from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)


def generate_mops_diff_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str | None:
    """Compare MOPS snapshots and generate diff report."""
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

    return _basic_diff(
        added=added,
        removed=removed,
        current_items=curr_items,
        has_previous=bool(previous_snapshot),
    )


def _extract_items(snapshot: str | None) -> list[dict[str, str]]:
    """Extract structured items from snapshot text."""
    if not snapshot:
        return []
    rows: list[dict[str, str]] = []
    in_list = False
    for line in snapshot.splitlines():
        s = line.strip()
        if s == "[即時資訊列表]":
            in_list = True
            continue
        if in_list and s.startswith("[") and not re.match(r"^\[\d+\]", s):
            break
        # 解析格式: [公司代碼] | 公司名稱 | 時間 | 標題 | URL (可選)
        # 支持多種格式變體
        m = re.match(r"^\[(\d+)\]\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)(?:\s*\|\s*(.+))?$", s)
        if m:
            rows.append(
                {
                    "code": m.group(1).strip(),
                    "company": m.group(2).strip(),
                    "time": m.group(3).strip(),
                    "title": m.group(4).strip(),
                    "url": (m.group(5) or "").strip(),
                }
            )
        else:
            # 嘗試備用格式（無 [代碼] 前綴）
            if in_list and s and not s.startswith("["):
                parts = [p.strip() for p in s.split("|")]
                if len(parts) >= 4:
                    try:
                        code_match = re.search(r"^(\d+)", parts[0])
                        if code_match:
                            rows.append({
                                "code": code_match.group(1),
                                "company": parts[1],
                                "time": parts[2],
                                "title": parts[3],
                                "url": parts[4] if len(parts) > 4 else "",
                            })
                    except Exception:
                        pass
    return rows


def _item_key(item: dict[str, str]) -> str:
    """Generate unique key for item - prioritize URL, fallback to code+time+title."""
    # 如果 URL 存在且不是佔位符，使用 URL
    url = (item.get("url") or "").strip()
    if url and url != "https://mops.twse.com.tw/..." and url != "#":
        return url
    # 否則使用公司代碼 + 時間 + 標題組合
    return f"{item.get('code', '')}|{item.get('time', '')}|{item.get('title', '')}"


def _basic_diff(
    *,
    added: list[dict[str, str]],
    removed: list[dict[str, str]],
    current_items: list[dict[str, str]],
    has_previous: bool,
) -> str:
    """Generate basic diff report without AI."""
    lines = [
        "MOPS 即時重大資訊更新｜首頁 > 即時重大資訊",
        f"本次新增：{len(added)} 筆",
        "-" * 40,
    ]
    if added:
        lines.append("新增即時重大資訊：")
        for i, item in enumerate(added[:15], 1):
            lines.append(
                f"  {i}. [{item['code']}] {item['company']} "
                f"({item['time']}) | {item['title']}"
            )
    elif not has_previous:
        lines.append("首次建立基準快照，目前前 15 筆：")
        for i, item in enumerate(current_items[:15], 1):
            lines.append(
                f"  {i}. [{item['code']}] {item['company']} "
                f"({item['time']}) | {item['title']}"
            )
    else:
        lines.append("資訊列表有變化，但沒有新增筆數。")

    return "\n".join(lines)


def _ai_diff(
    *,
    added: list[dict[str, str]],
    removed: list[dict[str, str]],
    api_key: str,
    model_name: str | None = None,
) -> str | None:
    """Generate AI-powered diff report using Gemini."""
    model = effective_gemini_model(model_name)

    # 構建提示文字
    added_block = "\n".join(
        [
            f"[{x['code']}] {x['company']} ({x['time']}) | {x['title']}"
            for x in added
        ]
    ) or "（無新增）"
    removed_block = "\n".join(
        [
            f"[{x['code']}] {x['company']} ({x['time']}) | {x['title']}"
            for x in removed
        ]
    ) or "（無移除）"

    prompt = f"""你是 MOPS 即時重大資訊差異摘要 Agent，輸出繁體中文通知。
【站點】公開資訊觀測站 MOPS
【區塊】首頁 > 即時重大資訊
【新增】
{added_block}
【移除】
{removed_block}

格式要求：
1) 第一行：MOPS 即時重大資訊更新｜首頁 > 即時重大資訊
2) 第二行：本次新增 N 筆、移除 M 筆
3) 列出最多 12 筆新增（含公司代碼、公司名稱、時間、標題，可不列網址）
4) 簡短分析本次更新的重點（如涉及哪些產業或通知類型）
5) 最後一句簡短結論
輸出純文字。
"""

    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.1,
        max_output_tokens=800,
    )
    return text[:2800] if text else None
