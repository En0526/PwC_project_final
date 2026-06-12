"""
Agent 2 - Labuan FSA media visual diff report agent.

Responsibilities:
  Compare previous/current Labuan media snapshot items and produce
  concise, notification-friendly summaries focused on meaningful items only.
"""
from __future__ import annotations

import os

from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)

_ITEM_TYPES = ["Press Releases", "Speeches", "Press Release", "Speech"]


def _is_item_line(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(f"[{t}]") for t in _ITEM_TYPES)


def _extract_items(snapshot: str | None) -> list[str]:
    if not snapshot:
        return []
    return [line.strip() for line in snapshot.splitlines() if _is_item_line(line)]


def _extract_field(snapshot: str | None, key: str) -> str:
    if not snapshot:
        return "未知"
    for line in snapshot.splitlines():
        if line.strip().startswith(f"[{key}]"):
            return line.split("]", 1)[-1].strip()
    return "未知"


def generate_labuanfsa_visual_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str:
    api_key = api_key or os.environ.get("GEMINI_API_KEY")

    if api_key and gemini_sdk_available():
        ai_report = _ai_visual_report(
            previous_snapshot=previous_snapshot,
            current_snapshot=current_snapshot,
            api_key=api_key,
            model_name=model_name,
        )
        if ai_report:
            return ai_report

    return _basic_visual_report(
        previous_snapshot=previous_snapshot,
        current_snapshot=current_snapshot,
    )


def _ai_visual_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
    api_key: str,
    model_name: str | None = None,
) -> str | None:
    model = effective_gemini_model(model_name)

    curr_items = _extract_items(current_snapshot)
    prev_items = _extract_items(previous_snapshot)

    curr_date = _extract_field(current_snapshot, "最新日期")
    prev_date = _extract_field(previous_snapshot, "最新日期")
    curr_count = _extract_field(current_snapshot, "項目總數")

    added_items = [item for item in curr_items if item not in prev_items]
    removed_items = [item for item in prev_items if item not in curr_items]

    if not added_items and not removed_items and previous_snapshot:
        return None

    added_block = "\n".join(f"{i+1}. {item}" for i, item in enumerate(added_items)) or "（無新增）"
    removed_block = "\n".join(f"- {item}" for item in removed_items) if removed_items else ""
    date_change = f"{prev_date} -> {curr_date}" if previous_snapshot else f"{curr_date}（首次建立基準）"

    prompt = f"""你是 Labuan FSA Media 通知精煉 Agent。
請根據以下資訊，產生簡潔、易讀、可通知的繁體中文摘要。

【最新日期】{date_change}
【本頁項目總數】{curr_count}

【新增條目】
{added_block}

{f"【移除條目】\n{removed_block}" if removed_block else ""}

輸出格式（純文字）：
Labuan FSA 媒體更新
最新日期：{date_change}
本頁共 {curr_count} 筆
────────────────────────
新增項目：
（列出新增）
{f"────────────────────────\n移除項目：\n（列出移除）" if removed_block else ""}
────────────────────────
重點摘要：
（2-3 點，每點以「•」開頭）

規則：
1. 只輸出列表中的實際條目，不要輸出系統欄位名稱。
2. 優先保留日期、類型（Press Releases / Speeches）與標題。
3. 若首次建立基準，請在重點摘要說明「首次建立監測基準」。
"""

    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.1,
        max_output_tokens=600,
    )
    return text[:2500] if text else None


def _basic_visual_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
) -> str:
    curr_items = _extract_items(current_snapshot)
    prev_items = _extract_items(previous_snapshot)

    prev_set = set(prev_items)
    curr_set = set(curr_items)

    added = [item for item in curr_items if item not in prev_set]
    removed = [item for item in prev_items if item not in curr_set]

    curr_date = _extract_field(current_snapshot, "最新日期")
    prev_date = _extract_field(previous_snapshot, "最新日期")
    curr_count = _extract_field(current_snapshot, "項目總數")

    lines = ["Labuan FSA 媒體更新"]
    if previous_snapshot:
        lines.append(f"最新日期：{prev_date} -> {curr_date}")
    else:
        lines.append(f"最新日期：{curr_date}（首次建立基準）")

    lines.append(f"本頁共 {curr_count} 筆")
    lines.append("-" * 32)

    if added:
        lines.append("新增項目：")
        for idx, item in enumerate(added, 1):
            lines.append(f"  {idx}. {item}")
    elif not previous_snapshot:
        lines.append("本次列表項目：")
        for idx, item in enumerate(curr_items, 1):
            lines.append(f"  {idx}. {item}")
    else:
        lines.append("與上次相同，無新增項目。")

    if removed:
        lines.append("-" * 32)
        lines.append("移除項目：")
        for item in removed:
            lines.append(f"  • {item}")

    return "\n".join(lines)
