"""Agent 3：先理解頁面有哪些主要區塊，再將使用者「監測目標」對位到對應區塊，產出給 Agent 1（擷取）的具體指令。

流程：結構摘要（標題／區塊） + 純文字摘要 → Gemini → JSON → `extraction_instruction` 交給
`gemini_service.extract_watch_content`（既有 Agent 1）做實際文字擷取與後續 diff。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from backend.services.gemini_generation import (
    gemini_sdk_available,
    generate_content_text,
    effective_gemini_model,
)


def _page_target_agent_enabled() -> bool:
    return (os.environ.get("PAGE_TARGET_AGENT_ENABLED") or "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _model_name() -> str:
    raw = (os.environ.get("PAGE_TARGET_AGENT_MODEL") or "").strip()
    if raw:
        return raw
    return effective_gemini_model(None)


def extract_heading_outline(html: str, max_headings: int = 48) -> str:
    """從 HTML 抽出 h1–h4 形成頁面區塊索引（給 Agent 3 對位用）。"""
    if not (html or "").strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    seen: set[str] = set()
    lines: list[str] = []
    for t in soup.find_all(["h1", "h2", "h3", "h4"]):
        txt = t.get_text(" ", strip=True)
        if not txt or len(txt) > 220:
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(txt)
        if len(lines) >= max_headings:
            break
    if not lines:
        return ""
    return "【頁面標題／區塊索引（依出現順序）】\n" + "\n".join(f"- {x}" for x in lines)


def _parse_json_obj(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


@dataclass
class PageTargetResolution:
    """Agent 3 輸出：供 Agent 1 使用的擷取指令與對位結果。"""

    extraction_instruction: str
    matched_section_names: list[str] = field(default_factory=list)
    page_sections_labeled: list[dict[str, str]] = field(default_factory=list)
    monitoring_scope_zh: str = ""
    user_target_echo: str = ""


def resolve_page_target(
    *,
    url: str,
    html: str,
    full_text: str,
    user_target: str,
    api_key: str,
) -> PageTargetResolution | None:
    """
    回傳對位結果；失敗或關閉時回傳 None（呼叫端沿用原始 user_target 給 Agent 1）。
    """
    if not _page_target_agent_enabled() or not gemini_sdk_available() or not (api_key or "").strip():
        return None
    ut = (user_target or "").strip()
    if not ut:
        return None

    outline = extract_heading_outline(html[:200_000])
    body_excerpt = (full_text or "")[:28_000]

    model = _model_name()

    prompt = f"""你是 **Agent 3（頁面理解與目標對位）**。任務分三步：
1. 根據【標題索引】與【純文字摘錄】理解此頁大致有哪些功能區塊（例如：最新消息、側欄、頁尾等）。
2. 對照使用者的【監測目標】，判斷應鎖定哪一個或數個區塊來監測「是否有更新」。
3. 產出一段給 **Agent 1（網頁區塊擷取）** 的具體指令 `extraction_instruction`：說明要保留哪些區塊的文字、可沿著哪些標題定位、應排除頁首導覽／頁尾／廣告等。指令要足够具體，使下游只需按文字擷取即可穩定做 diff。

網址（參考）：{url}

【使用者的監測目標】
{ut}

{outline}

【純文字摘錄（前段）】
{body_excerpt}

僅回傳一段 **合法 JSON**（不要 markdown、不要註解），格式如下：
{{
  "page_sections": [{{"name": "區塊名稱", "note": "一句話說明此區塊用途"}}],
  "matched_section_names": ["與監測目標最相關的標題名稱，可多個"],
  "monitoring_scope_zh": "用繁體中文一句話說明要比對的範圍",
  "extraction_instruction": "給 Agent 1 的完整指令（可用繁中或中英混合，必須具體）"
}}
若無法對位，仍要產出最佳努力的 extraction_instruction（例如僅擷取與關鍵字相關的段落）。
"""

    text = generate_content_text(api_key=api_key, model=model, prompt=prompt) or ""
    if not text.strip():
        return None

    data = _parse_json_obj(text.strip())
    if not data:
        return None

    instruction = (data.get("extraction_instruction") or "").strip()
    if not instruction:
        return None

    ms = data.get("matched_section_names")
    if not isinstance(ms, list):
        ms = []
    ms = [str(x).strip() for x in ms if str(x).strip()]

    ps = data.get("page_sections")
    sections: list[dict[str, str]] = []
    if isinstance(ps, list):
        for item in ps:
            if isinstance(item, dict):
                sections.append({
                    "name": str(item.get("name") or "").strip(),
                    "note": str(item.get("note") or "").strip(),
                })

    scope = str(data.get("monitoring_scope_zh") or "").strip()

    return PageTargetResolution(
        extraction_instruction=instruction,
        matched_section_names=ms[:12],
        page_sections_labeled=[p for p in sections if p.get("name")][:20],
        monitoring_scope_zh=scope,
        user_target_echo=ut,
    )


def page_target_diagnostic(res: PageTargetResolution | None) -> dict | None:
    if res is None:
        return None
    return {
        "role": "page_target_agent",
        "monitoring_scope_zh": res.monitoring_scope_zh,
        "matched_section_names": res.matched_section_names,
        "page_sections": res.page_sections_labeled,
        "instruction_preview": (res.extraction_instruction[:500] + "…")
        if len(res.extraction_instruction) > 500
        else res.extraction_instruction,
    }
