"""
Agent 2 - 行政院公報內容差異視覺化摘要 Agent

職責：
  在 Agent 1 確認有新卷期或新公報後，
  比對前後期的「公報條目」列表（法規、公告及送達等），
  產生聚焦、可讀的通知摘要，不顯示內部快照欄位雜訊。
"""
from __future__ import annotations

import os
import re

from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)

# 公報條目行的前綴格式（gazette_snapshot_text 產生的格式為「  [類型] 標題」）
_ITEM_TYPES = ["法規", "行政規則", "公告及送達", "處分", "人事", "其他", "公報"]
_METADATA_KEYS = {"卷期", "查詢條件", "出刊日期", "筆數", "公報列表"}


def _is_item_line(line: str) -> bool:
    """判斷此行是否為實際公報條目（非內部欄位）。"""
    stripped = line.strip()
    # 格式為 [法規] 標題 或 [公告及送達] 標題
    for t in _ITEM_TYPES:
        if stripped.startswith(f"[{t}]"):
            return True
    return False


def _extract_items(snapshot: str | None) -> list[str]:
    """從快照文字中只取出公報條目行，去掉前後空白。"""
    if not snapshot:
        return []
    return [line.strip() for line in snapshot.splitlines() if _is_item_line(line)]


def _extract_field(snapshot: str | None, key: str) -> str:
    """從快照文字中取出指定欄位值。"""
    if not snapshot:
        return "未知"
    for line in snapshot.splitlines():
        if line.strip().startswith(f"[{key}]"):
            return line.split("]", 1)[-1].strip()
    return "未知"


def generate_gazette_visual_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str:
    """
    Agent 2 主要函式：
    接收前後次公報快照，回傳聚焦於公報條目的可視化差異報告。
    若 Gemini 可用則用 AI 精煉，否則回退到基本格式輸出。
    """
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


# ---------------------------------------------------------------------------
# AI 視覺化報告
# ---------------------------------------------------------------------------

def _ai_visual_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
    api_key: str,
    model_name: str | None = None,
) -> str | None:
    model = effective_gemini_model(model_name)

    # 只傳公報條目給 AI，避免 AI 把快照欄位當作資料
    curr_items = _extract_items(current_snapshot)
    prev_items = _extract_items(previous_snapshot)

    curr_vol = _extract_field(current_snapshot, "卷期")
    prev_vol = _extract_field(previous_snapshot, "卷期")
    curr_date = _extract_field(current_snapshot, "出刊日期")
    curr_count = _extract_field(current_snapshot, "筆數")

    added_items = [item for item in curr_items if item not in prev_items]
    removed_items = [item for item in prev_items if item not in curr_items]

    # 若無實際差異，直接回 None（由呼叫端決定是否仍通知）
    if not added_items and not removed_items and previous_snapshot:
        return None

    added_block = "\n".join(f"{i+1}. {item}" for i, item in enumerate(added_items)) or "（無新增）"
    vol_change = f"{prev_vol} → {curr_vol}" if previous_snapshot else f"{curr_vol}（首次建立基準）"

    prompt = f"""你是「行政院公報通知精煉 Agent」。
請根據以下資訊，產生一份簡潔、易讀的繁體中文公報更新通知，聚焦在法規及公告內容，不要重複顯示欄位標籤。

【卷期】{vol_change}
【出刊日期】{curr_date}
【本期公報筆數】{curr_count}

【本期新增公報條目】
{added_block}

請以純文字輸出以下格式（不使用 Markdown 符號）：

行政院公報更新｜財政經濟篇
卷期：{vol_change}
出刊日期：{curr_date}
本期共 {curr_count}
────────────────────────
本期公報內容：
（依序列出新增條目，格式：序號. [類型] 簡明標題，不要超過一行）
────────────────────────
重點摘要：
（2-3 點，每點以「•」開頭，說明本期法規或公告的核心影響）

規則：
1. 只輸出有實際意義的公報條目（法規、行政規則、公告及送達等），不輸出欄位名稱或系統資訊。
2. 標題可縮短但不可扭曲原意。
3. 若為首次建立基準，重點摘要改為「首次建立監測基準，目前公報內容如上」。
4. 不要輸出任何移除項目或移除數量。
"""

    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.1,
        max_output_tokens=500,
    )
    return text[:2500] if text else None


# ---------------------------------------------------------------------------
# Fallback 基本視覺化報告（無 AI）
# ---------------------------------------------------------------------------

def _basic_visual_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
) -> str:
    """
    不依賴 AI，只比對公報條目行的差異（跳過欄位標籤），輸出清楚的基本報告。
    """
    curr_items = _extract_items(current_snapshot)
    prev_items = _extract_items(previous_snapshot)
    prev_set = set(prev_items)
    curr_set = set(curr_items)

    added = [item for item in curr_items if item not in prev_set]
    removed = [item for item in prev_items if item not in curr_set]

    curr_vol = _extract_field(current_snapshot, "卷期")
    prev_vol = _extract_field(previous_snapshot, "卷期")
    curr_date = _extract_field(current_snapshot, "出刊日期")
    curr_count = _extract_field(current_snapshot, "筆數")

    dash = "─" * 39
    lines = ["行政院公報更新｜財政經濟篇"]

    if previous_snapshot:
        lines.append(f"卷期：{prev_vol} → {curr_vol}")
    else:
        lines.append(f"卷期：{curr_vol}（首次建立基準）")

    lines += [f"出刊日期：{curr_date}", f"本期共 {curr_count}", dash]

    if added:
        lines.append("本期公報內容：")
        for i, item in enumerate(added, 1):
            lines.append(f"  {i}. {item}")
    elif not previous_snapshot:
        lines.append("本期公報內容：")
        for i, item in enumerate(curr_items, 1):
            lines.append(f"  {i}. {item}")
    else:
        lines.append("本期公報與上期一致，無新增項目。")

    return "\n".join(lines)
