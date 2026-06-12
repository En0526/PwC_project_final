"""
Agent 1 - Labuan FSA Media monitor agent.

Responsibilities:
  1. Parse Labuan FSA media page and extract the list area (date/type/title/link).
  2. Convert extracted data to a stable snapshot text for diff comparison.
  3. Use Gemini (optional) to analyze changes based on watch_description.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

from bs4 import BeautifulSoup

from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)

LABUANFSA_HOST = "labuanfsa.gov.my"
_MEDIA_PATH = "/resources/media"
_DATE_RE = re.compile(r"\b([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\b")
_DATE_TYPE_RE = re.compile(
    r"\b([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\s*\|\s*(Press Releases|Speeches|Press Release|Speech)\b",
    re.IGNORECASE,
)
_MEDIA_HREF_RE = re.compile(r"/resources/media/(press-releases|speeches)/", re.IGNORECASE)


def is_labuanfsa_url(url: str) -> bool:
    """Return True for Labuan FSA media URLs only."""
    lower_url = (url or "").lower()
    return LABUANFSA_HOST in lower_url and _MEDIA_PATH in lower_url


def extract_labuanfsa_structured(html: str) -> dict:
    """Extract media list items from Labuan FSA media page."""
    soup = BeautifulSoup(html or "", "html.parser")

    items_by_title: dict[str, dict] = {}
    base = "https://www.labuanfsa.gov.my"

    for a_tag in soup.find_all("a", href=True):
        href = (a_tag.get("href") or "").strip()
        if not _MEDIA_HREF_RE.search(href):
            continue

        title = _clean_title(a_tag.get_text(" ", strip=True))
        if not title or len(title) < 8:
            continue

        date_str, item_type = _find_date_type(a_tag, href)
        link = href if href.startswith("http") else f"{base}{href}"

        existing = items_by_title.get(title)
        if not existing:
            items_by_title[title] = {
                "type": item_type,
                "date": date_str,
                "title": title,
                "link": link,
            }
        else:
            if not existing.get("date") and date_str:
                existing["date"] = date_str
            if not existing.get("link") and link:
                existing["link"] = link
            if existing.get("type") == "Press Releases" and item_type == "Speeches":
                existing["type"] = item_type

    # Fallback for dynamic template payload where list items are embedded in JSON-like blocks.
    if not items_by_title:
        for item in _extract_items_from_payload(html or ""):
            title = item.get("title") or ""
            if title and title not in items_by_title:
                items_by_title[title] = item

    items = sorted(items_by_title.values(), key=_item_sort_key)
    # Keep a bounded newest window to match the visible media list area and reduce noise.
    items = items[:40]
    latest_date = next((it.get("date") for it in items if it.get("date")), "")

    return {
        "latest_date": latest_date,
        "total_count": len(items),
        "items": items,
    }


def _extract_items_from_payload(html: str) -> list[dict]:
    items: list[dict] = []
    if not html:
        return items

    normalized = html.replace('\\"', '"').replace('\\/', '/')

    object_re = re.compile(r"\{[^{}]{0,2200}\}")
    for obj_m in object_re.finditer(normalized):
        block = obj_m.group(0)
        href_m = re.search(
            r'"[^"\\]+"\s*:\s*"(resources/media/(?:press-releases|speeches)/[^"\\]+)"',
            block,
            re.IGNORECASE,
        )
        if not href_m:
            continue

        href = href_m.group(1)

        item_type = "Speeches" if "speeches/" in href.lower() else "Press Releases"
        type_m = re.search(r'"[^"\\]+"\s*:\s*"(Press Releases|Speeches|Press Release|Speech)"', block, re.IGNORECASE)
        if type_m:
            item_type = _normalize_type(type_m.group(1))

        date_text = ""
        date_m = re.search(r'"[^"\\]+"\s*:\s*"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})(?:,\s*\d{1,2}:\d{2}\s*[AP]M)?"', block)
        if date_m:
            date_text = date_m.group(1).strip()

        # Candidate values inside block; choose the longest meaningful non-url text as title.
        values = re.findall(r'"[^"\\]+"\s*:\s*"([^"\\]+)"', block)
        title = ""
        for value in values:
            v = _clean_title(value)
            if not v or len(v) < 8:
                continue
            if v.startswith("resources/media/"):
                continue
            if _DATE_RE.search(v):
                continue
            if v in ("Press Releases", "Speeches", "Press Release", "Speech"):
                continue
            if len(v) > len(title):
                title = v

        if not title:
            continue

        items.append(
            {
                "type": item_type,
                "date": date_text,
                "title": title,
                "link": f"https://www.labuanfsa.gov.my/{href.lstrip('/')}",
            }
        )

    # Deduplicate by title while keeping first occurrence order.
    dedup: dict[str, dict] = {}
    for it in items:
        title = it.get("title") or ""
        if title and title not in dedup:
            dedup[title] = it
    return list(dedup.values())


def _item_sort_key(item: dict) -> tuple[int, float, str]:
    date_text = (item.get("date") or "").strip()
    if date_text:
        try:
            ts = datetime.strptime(date_text, "%b %d, %Y").timestamp()
            return (0, -ts, item.get("title") or "")
        except ValueError:
            pass
    return (1, 0.0, item.get("title") or "")


def _find_date_type(a_tag, href: str) -> tuple[str, str]:
    # Prefer href-based type, then nearby text override if present.
    item_type = "Speeches" if "speech" in (href or "").lower() else "Press Releases"

    search_nodes = []
    parent = a_tag.find_parent()
    if parent:
        search_nodes.append(parent)
        search_nodes.extend(list(parent.parents)[:4])

    for node in search_nodes:
        text = node.get_text(" ", strip=True)
        m = _DATE_TYPE_RE.search(text)
        if m:
            return m.group(1).strip(), _normalize_type(m.group(2).strip())

    for node in search_nodes:
        text = node.get_text(" ", strip=True)
        m = _DATE_RE.search(text)
        if m:
            return m.group(1).strip(), item_type

    return "", item_type


def _normalize_type(raw: str) -> str:
    if "speech" in (raw or "").lower():
        return "Speeches"
    return "Press Releases"


def _clean_title(title: str) -> str:
    text = (title or "").strip()
    text = text.replace("��", "'")
    text = re.sub(r"^on\s+", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text)


def labuanfsa_snapshot_text(data: dict) -> str:
    """Serialize structured data into stable snapshot text."""
    lines = [
        f"[最新日期] {data.get('latest_date', '未知')}",
        f"[項目總數] {data.get('total_count', 0)}",
        "[媒體列表]",
    ]
    for item in data.get("items", []):
        date_text = (item.get("date") or "").strip()
        prefix = f"{date_text} | " if date_text else ""
        lines.append(f"  [{item.get('type', 'Press Releases')}] {prefix}{item.get('title', '')}")
    return "\n".join(lines)


def analyze_labuanfsa_change(
    *,
    watch_description: str,
    current_snapshot: str,
    previous_snapshot: str | None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str | None:
    """Generate Agent 1 analysis report with Gemini."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key or not gemini_sdk_available():
        return None

    model = effective_gemini_model(model_name)

    previous_block = (previous_snapshot or "").strip() or "（本次為首次擷取，無前次資料）"

    prompt = f"""你是 Labuan FSA Media 監測 Agent。
請依照使用者監測指令，比對前後快照並回覆繁體中文重點。

【使用者監測指令】
{watch_description}

【本次快照】
{current_snapshot}

【上次快照】
{previous_block}

請輸出純文字，格式如下：
1. 最新日期是否更新（前次 -> 本次）
2. 本次項目總數
3. 新增項目（若無則寫「無新增」）
4. 移除項目（若無則寫「無移除」）
5. 監測結論（1 句）

規則：
- 僅根據快照內容回答，不可臆測。
- 只關注 Media 列表中的日期、類型、標題。
"""

    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.1,
        max_output_tokens=500,
    )
    return text[:2500] if text else None
