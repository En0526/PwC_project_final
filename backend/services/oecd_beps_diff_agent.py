"""Agent 2 - OECD BEPS 頁面差異判讀。

比較 Latest insights 與 Related publications 兩個區塊的新舊快照，
偵測新增 / 移除項目，並可抓取新文章內容提供豐富通知摘要。
"""
from __future__ import annotations

import os
import re

from backend.services.oecd_beps_monitor_agent import (
    SECTION_INSIGHTS,
    SECTION_PUBLICATIONS,
    parse_oecd_beps_snapshot,
)
from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)

OECD_BASE = "https://www.oecd.org"


def generate_oecd_beps_diff_report(
    *,
    previous_snapshot: str | None,
    current_snapshot: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str | None:
    """比較 OECD BEPS 快照差異並回傳通知摘要。

    若無差異且 previous_snapshot 存在則回傳 None（不觸發通知）。
    """
    curr_sections = parse_oecd_beps_snapshot(current_snapshot)
    prev_sections = parse_oecd_beps_snapshot(previous_snapshot) if previous_snapshot else {}

    if not curr_sections:
        return None

    # 分區塊計算新增 / 移除
    section_diffs: dict[str, dict] = {}
    any_change = False

    for section_name in (SECTION_INSIGHTS, SECTION_PUBLICATIONS):
        curr_items = curr_sections.get(section_name, [])
        prev_items = prev_sections.get(section_name, [])
        prev_keys = {_item_key(i) for i in prev_items}
        curr_keys = {_item_key(i) for i in curr_items}
        added = [i for i in curr_items if _item_key(i) not in prev_keys]
        removed = [i for i in prev_items if _item_key(i) not in curr_keys]
        if added or removed:
            any_change = True
        section_diffs[section_name] = {
            "added": added,
            "removed": removed,
            "curr_items": curr_items,
        }

    if not any_change and previous_snapshot:
        return None

    # 嘗試 AI 摘要
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if api_key and gemini_sdk_available():
        ai_text = _ai_diff(
            section_diffs=section_diffs,
            has_previous=bool(previous_snapshot),
            api_key=api_key,
            model_name=model_name,
        )
        if ai_text:
            return ai_text

    return _basic_diff(
        section_diffs=section_diffs,
        has_previous=bool(previous_snapshot),
    )


# ---------------------------------------------------------------------------
# 內部工具
# ---------------------------------------------------------------------------

def _item_key(item: dict) -> str:
    """以 URL 作為唯一鍵；無 URL 則用標題+日期。"""
    url = (item.get("url") or "").strip()
    if url:
        return url
    return f"{item.get('date', '')}|{item.get('title', '')}"


def _fmt_item(item: dict, include_url: bool = False) -> str:
    date = item.get("date", "")
    tag = item.get("tag", "")
    title = item.get("title", "")
    url = item.get("url", "")
    pages = item.get("pages", "")
    subtitle = item.get("subtitle", "")

    parts = []
    if date:
        parts.append(f"[{date}]")
    if tag:
        parts.append(f"[{tag}]")
    parts.append(title)
    if subtitle:
        parts.append(f"({subtitle})")
    if pages:
        parts.append(f"- {pages}")
    line = " ".join(parts)
    if include_url and url:
        full_url = url if url.startswith("http") else OECD_BASE + url
        line += f"\n      {full_url}"
    return line


def _fetch_article_summary(url: str) -> str:
    """嘗試抓取文章內容的前幾段，回傳簡短摘要文字。失敗則回傳空字串。"""
    if not url:
        return ""
    full_url = url if url.startswith("http") else OECD_BASE + url
    try:
        from backend.services.scraper import fetch_page_playwright
        from bs4 import BeautifulSoup
        html, _ = fetch_page_playwright(full_url, timeout=20)
        soup = BeautifulSoup(html, "html.parser")
        # 取主要內容區域的段落文字
        main = soup.find("main") or soup.find("div", class_=lambda x: x and "article" in " ".join(x).lower())
        if main:
            paragraphs = main.find_all("p")
            text = " ".join(p.get_text(strip=True) for p in paragraphs[:5])
            text = re.sub(r"\s+", " ", text).strip()
            return text[:600]
    except Exception:
        pass
    return ""


def _basic_diff(
    *,
    section_diffs: dict[str, dict],
    has_previous: bool,
) -> str:
    lines = ["OECD BEPS 頁面更新", "─" * 36]

    for section_name in (SECTION_INSIGHTS, SECTION_PUBLICATIONS):
        diff = section_diffs.get(section_name, {})
        added = diff.get("added", [])
        removed = diff.get("removed", [])
        curr_items = diff.get("curr_items", [])

        if not added and not removed and has_previous:
            continue

        lines.append(f"\n【{section_name}】")
        if not has_previous:
            lines.append(f"首次建立基準快照（共 {len(curr_items)} 項）")
            for item in curr_items[:6]:
                lines.append(f"  • {_fmt_item(item)}")
        else:
            if added:
                lines.append(f"新增 {len(added)} 項：")
                for item in added[:8]:
                    lines.append(f"  + {_fmt_item(item, include_url=True)}")
            if removed:
                lines.append(f"移除 {len(removed)} 項：")
                for item in removed[:5]:
                    lines.append(f"  - {_fmt_item(item)}")

    return "\n".join(lines)


def _ai_diff(
    *,
    section_diffs: dict[str, dict],
    has_previous: bool,
    api_key: str,
    model_name: str | None = None,
) -> str | None:
    model = effective_gemini_model(model_name)

    # 組建 AI 提示所需的內容
    blocks: list[str] = []
    for section_name in (SECTION_INSIGHTS, SECTION_PUBLICATIONS):
        diff = section_diffs.get(section_name, {})
        added = diff.get("added", [])
        removed = diff.get("removed", [])
        curr_items = diff.get("curr_items", [])

        if not has_previous:
            items_text = "\n".join(f"  • {_fmt_item(i)}" for i in curr_items[:10])
            blocks.append(f"【{section_name}】（首次快照，共 {len(curr_items)} 項）\n{items_text}")
            continue

        if not added and not removed:
            blocks.append(f"【{section_name}】無變動")
            continue

        section_lines = [f"【{section_name}】"]
        if added:
            section_lines.append(f"新增 {len(added)} 項：")
            for item in added[:8]:
                section_lines.append(f"  + {_fmt_item(item)}")
                # 嘗試抓取文章內容以豐富說明
                summary = _fetch_article_summary(item.get("url", ""))
                if summary:
                    section_lines.append(f"    內容摘錄：{summary[:300]}")
        if removed:
            section_lines.append(f"移除 {len(removed)} 項：")
            for item in removed[:5]:
                section_lines.append(f"  - {_fmt_item(item)}")
        blocks.append("\n".join(section_lines))

    diff_text = "\n\n".join(blocks)

    prompt = f"""你是 OECD BEPS 政策追蹤助理，負責整理頁面變動通知。請用繁體中文輸出，語氣專業簡潔。

以下是偵測到的頁面變動：
{diff_text}

請依照下列格式輸出（純文字，不要 Markdown）：
第一行：OECD BEPS 頁面更新
第二行：摘要（幾個區塊有變動，共新增幾項）
空一行
接著分兩個區塊（Latest insights、Related publications）列出新增項目，每項包含：
  - 日期、類型標籤、標題
  - 若有內容摘錄，用 1~2 句說明該文件的重點
最後一句結論。
整體不超過 600 字。
"""
    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.1,
        max_output_tokens=900,
    )
    return text[:3000] if text else None
