"""AI 差異摘要服務（Google AI Studio / Gemini）。"""
import os

from backend.services.gazette_monitor_agent import is_gazette_url, analyze_gazette_change
from backend.services.gazette_diff_agent import generate_gazette_visual_report
from backend.services.labuanfsa_monitor_agent import is_labuanfsa_url, analyze_labuanfsa_change
from backend.services.labuanfsa_diff_agent import generate_labuanfsa_visual_report
from backend.services.gemini_generation import (
    effective_gemini_model,
    gemini_sdk_available,
    generate_content_text,
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def generate_diff_summary(
    *,
    site_name: str,
    url: str,
    source_type: str,
    raw_diff_summary: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str | None:
    """
    產生 AI 差異摘要。失敗回傳 None（由呼叫端 fallback）。
    """
    if not _env_bool("AI_SUMMARY_ENABLED", False):
        return None

    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key or not gemini_sdk_available():
        return None

    model = effective_gemini_model(model_name)

    prompt = f"""你是網站變更摘要助手。請根據給定差異，輸出「精簡、可讀」的繁體中文摘要。

【網站名稱】
{site_name}

【網址】
{url}

【資料來源】
{source_type.upper()}

【原始差異摘要】
{raw_diff_summary}

請遵守：
1) 只根據提供內容，不可臆測。
2) 最多 3 點，每點 1 句。
3) 盡量指出「新增／移除／影響」。
4) 純文字輸出，不要加 Markdown 標題。
"""

    text = generate_content_text(
        api_key=api_key,
        model=model,
        prompt=prompt,
        temperature=0.2,
        max_output_tokens=280,
    )
    if not text:
        return None
    return text[:1000]


def generate_diff_summary_for_url(
    *,
    url: str,
    site_name: str,
    source_type: str,
    raw_diff_summary: str,
    old_snapshot: str | None = None,
    new_snapshot: str | None = None,
    watch_description: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> str | None:
    """
    智慧路由版 diff summary：
    - 若為行政院公報網址，優先呼叫 Agent 1（監測報告）再呼叫 Agent 2（視覺化差異）。
    - 其他網址使用原始 generate_diff_summary。
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")

    if is_gazette_url(url):
        # Agent 1：監測分析（依 watch_description 解讀變更）
        monitor_report = None
        if watch_description and new_snapshot:
            monitor_report = analyze_gazette_change(
                watch_description=watch_description,
                current_snapshot=new_snapshot,
                previous_snapshot=old_snapshot,
                api_key=api_key,
                model_name=model_name,
            )

        # Agent 2：視覺化差異報告
        visual_report = generate_gazette_visual_report(
            previous_snapshot=old_snapshot,
            current_snapshot=new_snapshot or raw_diff_summary,
            api_key=api_key,
            model_name=model_name,
        )

        parts = []
        if monitor_report:
            parts.append(monitor_report)
        if visual_report:
            parts.append(visual_report)
        if parts:
            return "\n\n".join(parts)[:3000]

    if is_labuanfsa_url(url):
        # Agent 1: monitoring analysis from watch_description.
        monitor_report = None
        if watch_description and new_snapshot:
            monitor_report = analyze_labuanfsa_change(
                watch_description=watch_description,
                current_snapshot=new_snapshot,
                previous_snapshot=old_snapshot,
                api_key=api_key,
                model_name=model_name,
            )

        # Agent 2: visual diff report for meaningful list changes.
        visual_report = generate_labuanfsa_visual_report(
            previous_snapshot=old_snapshot,
            current_snapshot=new_snapshot or raw_diff_summary,
            api_key=api_key,
            model_name=model_name,
        )

        parts = []
        if monitor_report:
            parts.append(monitor_report)
        if visual_report:
            parts.append(visual_report)
        if parts:
            return "\n\n".join(parts)[:3000]

    # 其他網站走原始流程
    return generate_diff_summary(
        site_name=site_name,
        url=url,
        source_type=source_type,
        raw_diff_summary=raw_diff_summary,
        api_key=api_key,
        model_name=model_name,
    )
