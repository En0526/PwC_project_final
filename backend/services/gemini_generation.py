"""Google Gemini 呼叫統一走 google-genai（Developer API／AI Studio）。"""
from __future__ import annotations

import os
from typing import Any

_SDK_UNSET = object()
_genai_sdk: Any = _SDK_UNSET


def _load_genai_sdk() -> Any | None:
    global _genai_sdk
    if _genai_sdk is not _SDK_UNSET:
        return _genai_sdk
    try:
        from google import genai as google_genai  # type: ignore[no-redef]
        _genai_sdk = google_genai
    except ImportError:
        _genai_sdk = None
    return _genai_sdk


def gemini_sdk_available() -> bool:
    return _load_genai_sdk() is not None


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def effective_gemini_model(explicit: str | None = None) -> str:
    """
    解析實際使用的模型 id。
    優先序：呼叫端 explicit → 環境變數 GEMINI_MODEL → AI_SUMMARY_MODEL → 預設。
    """
    if (explicit or "").strip():
        return explicit.strip()
    for key in ("GEMINI_MODEL", "AI_SUMMARY_MODEL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return DEFAULT_GEMINI_MODEL


def generate_content_text(
    *,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> str | None:
    """回傳模型純文字輸出；失敗回傳 None。"""
    sdk = _load_genai_sdk()
    if not sdk or not (api_key or "").strip():
        return None
    try:
        from google.genai import types
    except ImportError:
        return None

    cfg_kwargs: dict[str, Any] = {}
    if temperature is not None:
        cfg_kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        cfg_kwargs["max_output_tokens"] = max_output_tokens
    config = types.GenerateContentConfig(**cfg_kwargs) if cfg_kwargs else None
    client = sdk.Client(api_key=api_key.strip())
    try:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        text = (getattr(response, "text", None) or "").strip()
        return text if text else None
    except Exception:
        return None
