"""
Agent 1 - 行政院公報資訊網 專屬監測 Agent

職責：
  1. 解析行政院公報頁面，結構化擷取卷期、查詢條件、筆數、公報列表
  2. 將結構化資料轉為穩定快照文字（用於前後比對）
  3. 根據使用者 watch_description，用 Gemini 分析變更重點
"""
from __future__ import annotations

import os
import re

from bs4 import BeautifulSoup

from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)

GAZETTE_HOST = "gazette.nat.gov.tw"


def is_gazette_url(url: str) -> bool:
    """判斷是否為行政院公報資訊網的 URL。"""
    return GAZETTE_HOST in (url or "").lower()


# ---------------------------------------------------------------------------
# 結構化解析（Agent 1 核心）
# ---------------------------------------------------------------------------

def extract_gazette_structured(html: str) -> dict:
    """
    從公報頁面 HTML 解析出關鍵結構資料：
    {
        "volume_issue": "第032卷第074期",   # 卷期（Box 1）
        "filter_tag": "財政經濟篇",          # 查詢條件篇別（Box 2）
        "publish_date": "2026-04-27",        # 出刊日期
        "total_count": "共3筆資料",          # 筆數資訊（Box 3）
        "items": [
            {"type": "法規", "title": "...", "link": "..."},
            ...
        ],
    }
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {
        "volume_issue": "",
        "filter_tag": "",
        "publish_date": "",
        "total_count": "",
        "items": [],
    }

    # ── Box 1：卷期號碼 ─────────────────────────────────────────────────────
    # 頁面通常有「第 032 卷 第 074 期」等文字，先找精確模式
    vol_pattern = re.compile(r"第\s*(\d{3})\s*卷\s*第\s*(\d{3})\s*期")
    page_text = soup.get_text(" ")
    vol_match = vol_pattern.search(page_text)
    if vol_match:
        result["volume_issue"] = f"第{vol_match.group(1)}卷第{vol_match.group(2)}期"

    # ── Box 2：查詢條件篇別 ──────────────────────────────────────────────────
    # 頁面有「查詢條件：　財政經濟篇✕」的標籤
    condition_label = soup.find(string=re.compile(r"查詢條件"))
    if condition_label:
        parent = condition_label.find_parent()
        if parent:
            tag_text = parent.get_text(" ", strip=True)
            # 抓「篇」字前的分類名
            m = re.search(r"查詢條件[：:＊*\s]+([^\s✕×x]+篇)", tag_text)
            if m:
                result["filter_tag"] = m.group(1).strip()
    # fallback：直接搜尋頁面文字
    if not result["filter_tag"]:
        ft_match = re.search(r"查詢條件[：:＊*\s]*([^\s✕×x\n]+篇)", page_text)
        if ft_match:
            result["filter_tag"] = ft_match.group(1).strip()

    # ── 出刊日期 ─────────────────────────────────────────────────────────────
    date_match = re.search(r"出刊日期[：:\s]*(\d{4}-\d{2}-\d{2})", page_text)
    if date_match:
        result["publish_date"] = date_match.group(1)

    # ── Box 3：筆數資訊 ──────────────────────────────────────────────────────
    count_match = re.search(r"共\s*(\d+)\s*筆資料", page_text)
    if count_match:
        result["total_count"] = f"共{count_match.group(1)}筆資料"

    # ── 公報列表 ─────────────────────────────────────────────────────────────
    # 頁面的每筆正式公報都連到 detail.do；browseHistory 等功能連結不算項目。
    base_url = "https://gazette.nat.gov.tw"
    seen_titles: set[str] = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "")
        if "detail.do" not in href:
            continue
        title = a_tag.get_text(strip=True)
        if not title or title in seen_titles or len(title) < 4:
            continue
        seen_titles.add(title)

        # 取公報類型（用項目前方最近的類型標籤判斷）
        item_type = _guess_item_type(a_tag, soup)

        full_link = href if href.startswith("http") else base_url + href
        result["items"].append({
            "type": item_type,
            "title": title,
            "link": full_link,
        })

    return result


def _guess_item_type(a_tag, soup) -> str:
    """嘗試從鄰近 DOM 節點推斷公報類型（法規 / 公告及送達 / 行政規則 …）。"""
    known_types = ["法規", "行政規則", "公告及送達", "處分", "人事", "其他"]
    for text_node in a_tag.find_all_previous(string=True):
        text = text_node.strip()
        if text in known_types:
            return text

    # 往上找最近的父容器，看是否有類型文字
    for parent in a_tag.parents:
        text = parent.get_text(" ", strip=True)
        for t in known_types:
            if t in text:
                return t
        if parent.name in ("table", "div", "li", "tr") and parent != soup:
            break
    return "公報"


# ---------------------------------------------------------------------------
# 快照文字（穩定格式，用於 diff 比對）
# ---------------------------------------------------------------------------

def gazette_snapshot_text(data: dict) -> str:
    """
    將結構化資料轉為穩定的快照文字，供前後次比對使用。
    格式固定，不含動態時間戳，確保只有內容變化時 hash 才會改變。
    """
    lines = [
        f"[卷期] {data.get('volume_issue', '未知')}",
        f"[查詢條件] {data.get('filter_tag', '未知')}",
        f"[出刊日期] {data.get('publish_date', '未知')}",
        f"[筆數] {data.get('total_count', '未知')}",
        "[公報列表]",
    ]
    for item in data.get("items", []):
        lines.append(f"  [{item.get('type', '公報')}] {item.get('title', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini 智慧分析（依 watch_description 指令回傳監測結果）
# ---------------------------------------------------------------------------

def analyze_gazette_change(
    *,
    watch_description: str,
    current_snapshot: str,
    previous_snapshot: str | None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str | None:
    """
    Agent 1 主要分析函式：
    根據使用者 watch_description，比對前後快照，
    以繁體中文回傳結構化監測報告。
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key or not gemini_sdk_available():
        return None

    model = effective_gemini_model(model_name)

    has_previous = bool(previous_snapshot and previous_snapshot.strip())
    prev_block = previous_snapshot.strip() if has_previous else "（本次為首次擷取，無前次資料）"

    prompt = f"""你是「行政院公報資訊網監測 Agent」。
使用者希望你依據以下指令，比對公報頁面的前後次快照，判斷是否有值得注意的更新。

【使用者監測指令】
{watch_description}

【本次快照】
{current_snapshot}

【上次快照】
{prev_block}

請依照以下格式，用繁體中文輸出監測報告（純文字，不加 Markdown 標題符號）：

1. 卷期是否有變化（填寫前後卷期）
2. 查詢條件確認（財政經濟篇是否仍在篩選中）
3. 本期筆數
4. 新增公報項目列表（若無變化則寫「本期與上期相同，無新增」）
5. 監測結論（一句話：是否有新公報、需注意什麼）

若本次為首次擷取，則說明目前狀態即可，並標記「首次建立基準快照」。
"""

    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.1,
        max_output_tokens=400,
    )
    return text[:2000] if text else None
